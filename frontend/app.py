"""Streamlit organizer/member test console for the GDG backend challenge."""
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env')
API = os.getenv('API_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
st.set_page_config(page_title='WorkshopFlow | GDG Backend Task 2',
                   page_icon='📨', layout='wide', initial_sidebar_state='expanded')
st.markdown('''<style>
.stApp {background: #0b1220; color: #eaf1ff;}
[data-testid="stSidebar"] {background: #111d31;}
h1,h2,h3 {letter-spacing:-.03em;}
[data-testid="stMetric"] {background:#172740; border:1px solid #293c5b;
 border-radius:14px; padding:15px;}
div.stButton>button[kind="primary"] {background:#3985f6; border-color:#3985f6;}
[data-testid="stDataFrame"] {border-radius:10px;}
</style>''', unsafe_allow_html=True)

if 'token' not in st.session_state:
    st.session_state.token = None
if 'profile' not in st.session_state:
    st.session_state.profile = None

def call(method, path, data=None, *, token=None):
    headers = {'Authorization': f'Bearer {token or st.session_state.token}'} if (token or st.session_state.token) else {}
    try:
        response = requests.request(method, API + path, headers=headers, json=data, timeout=5)
        obj = response.json()
        if response.status_code >= 400:
            return None, f'{response.status_code}: {obj.get("error", "Request rejected")}'
        return obj, None
    except requests.RequestException as exc:
        return None, f'API unavailable ({type(exc).__name__}). Start Django on port 8000.'
    except ValueError:
        return None, 'Backend returned a non-JSON response.'

def execute(method, path, data=None, success=None):
    result, error = call(method, path, data)
    if error:
        st.error(error)
    elif success:
        st.success(success)
    return result

def render_records(title, items):
    st.subheader(title)
    if items:
        st.dataframe(items, use_container_width=True, hide_index=True)
    else:
        st.info('No records yet.')

st.sidebar.markdown('## 📨 WorkshopFlow')
st.sidebar.caption('GDG TECH · Backend Task 2 · v1')

if not st.session_state.token:
    st.title('Workshop Registration & Notification Reliability')
    st.write('Sign in to the local test environment. Registration commits immediately; notifications run asynchronously.')
    left, right = st.columns([1, 1])
    with left:
        with st.form('login'):
            email = st.text_input('Email', value='organizer@demo.local')
            password = st.text_input('Password', type='password', value='Demo@12345')
            submitted = st.form_submit_button('Sign in', use_container_width=True, type='primary')
        if submitted:
            result, error = call('POST', '/api/auth/login/', {'email': email, 'password': password})
            if error:
                st.error(error)
            else:
                st.session_state.token = result['token']
                st.session_state.profile = result['user']
                st.rerun()
    with right:
        st.info('Sample accounts are created with `python manage.py seed_demo`.')
        st.code('organizer@demo.local  /  Demo@12345\nalex@demo.local       /  Demo@12345\nsam@demo.local        /  Demo@12345')
        st.markdown('**System services**: Django API 8000, mock HTTP 9100, background worker, MySQL 3306.')
    st.stop()

me = st.session_state.profile
st.sidebar.write(f'**{me["full_name"]}**')
st.sidebar.caption(me['role'])
if st.sidebar.button('Log out', use_container_width=True):
    st.session_state.token = None
    st.session_state.profile = None
    st.rerun()
if st.sidebar.button('Refresh data', use_container_width=True):
    st.rerun()

st.title('WorkshopFlow')
st.caption('Transactional workshops • Durable outbox • Automatic retries • Idempotent mock delivery')
health, h_error = call('GET', '/api/health/')
if h_error:
    st.error(h_error)
else:
    st.caption(f'Backend: {health["status"]} · Database: {health["database"]} · Authenticated as {me["email"]}')

is_organizer = me['role'] == 'ORGANIZER'
if is_organizer:
    dashboard_tab, workshops_tab, ops_tab, audit_tab, guide_tab = st.tabs(
        ['Overview', 'Workshops', 'Notification operations', 'Audit', 'Test guide'])
else:
    workshops_tab, my_tab, guide_tab = st.tabs(['Available workshops', 'My registrations', 'Test guide'])

if is_organizer:
    with dashboard_tab:
        stats, err = call('GET', '/api/stats/')
        if err:
            st.error(err)
        else:
            a, b, c, d = st.columns(4)
            a.metric('Workshops', stats['workshops'])
            b.metric('Registrations', stats['registrations'])
            c.metric('Delivered', stats['notifications']['DELIVERED'])
            d.metric('Pending / retry / inflight', sum(v for k,v in stats['notifications'].items() if k != 'DELIVERED'))
            st.caption('These are database-derived counts, not mock-service claims.')
            st.bar_chart({'status': list(stats['notifications'].keys()), 'events': list(stats['notifications'].values())}, x='status', y='events')
        recent, err = call('GET', '/api/outbox/')
        if not err:
            render_records('Recent notification events', recent['events'][:12])

with workshops_tab:
    my_registered = set()
    if not is_organizer:
        mine, _mine_error = call('GET', '/api/registrations/mine/')
        if mine:
            my_registered = {int(r['workshop_id']) for r in mine.get('registrations', [])}
    if is_organizer:
        with st.expander('Create a workshop', expanded=False):
            with st.form('create_workshop'):
                title = st.text_input('Title', value='Database Transactions and Resilient APIs')
                desc = st.text_area('Description', value='A practical session on reliability and message delivery.')
                c1, c2, c3 = st.columns(3)
                with c1:
                    d = st.date_input('Date', value=date.today() + timedelta(days=7), min_value=date.today())
                with c2:
                    t = st.time_input('Start time', value=time(hour=14))
                with c3:
                    tz = st.selectbox('Time zone', ['Asia/Kolkata', 'UTC'])
                cap = st.number_input('Capacity (0 = unlimited)', min_value=0, max_value=100000, value=30)
                create = st.form_submit_button('Create workshop', type='primary')
            if create:
                starts = datetime.combine(d, t).replace(tzinfo=ZoneInfo(tz)).isoformat()
                execute('POST', '/api/workshops/', {'title': title, 'description': desc,
                        'starts_at': starts, 'capacity': None if cap == 0 else int(cap)},
                        'Workshop created successfully.')
    data, err = call('GET', '/api/workshops/')
    if err:
        st.error(err)
    else:
        workshops_list = data.get('workshops', [])
        if not workshops_list:
            st.info('There are no workshops. Sign in as organizer and create one.')
        for w in workshops_list:
            icon = '🟩' if w['status'] == 'OPEN' else '🟥'
            with st.container(border=True):
                st.subheader(f'{icon} {w["title"]}')
                st.write(w.get('description', ''))
                st.caption(f'Workshop #{w["id"]} · {w["starts_at"]} · {w["registrations"]} registered · '
                           f'{"Unlimited capacity" if w["seats_left"] is None else str(w["seats_left"]) + " seats left"}')
                if is_organizer:
                    if w['created_by_id'] == me['id']:
                        if w['status'] == 'OPEN':
                            if st.button('Cancel and queue every member notification', key=f'cancel_{w["id"]}'):
                                done = execute('POST', f'/api/workshops/{w["id"]}/cancel/',
                                               success='Workshop cancelled. All registered members were queued.')
                                if done:
                                    st.rerun()
                        with st.expander('View registered members'):
                            people, problem = call('GET', f'/api/workshops/{w["id"]}/registrants/')
                            if problem:
                                st.error(problem)
                            elif people:
                                render_records('Registrants', people['registrants'])
                elif w['id'] in my_registered:
                    st.success('You are registered for this workshop.')
                elif w['status'] == 'OPEN' and (w['seats_left'] is None or w['seats_left'] > 0):
                    if st.button('Register for this workshop', key=f'register_{w["id"]}', type='primary'):
                        result = execute('POST', f'/api/workshops/{w["id"]}/register/',
                                         success='Registration saved. Confirmation is queued asynchronously.')
                        if result:
                            st.json(result)
                else:
                    st.caption('Registration closed.')

if not is_organizer:
    with my_tab:
        data, err = call('GET', '/api/registrations/mine/')
        if err:
            st.error(err)
        else:
            render_records('Your saved registrations', data['registrations'])
            st.info('Refreshing this page does not resubmit a registration. Each workshop accepts a member only once.')

if is_organizer:
    with ops_tab:
        st.write('Force a mock outage, register as a member, watch the outbox retry, then restore the mock service.')
        state, problem = call('GET', '/api/mock/status/')
        if problem:
            st.warning(problem)
        else:
            x, y, z = st.columns(3)
            x.metric('Mock mode', state['mode'])
            y.metric('Unique deliveries at mock', state['delivered_unique'])
            z.metric('HTTP requests seen', state['requests_seen'])
        new_mode = st.selectbox('Notification service behaviour',
                                ['healthy', 'always_503', 'timeout', 'flaky'],
                                help='flaky fails first two requests per unique event.')
        if st.button('Apply mock behaviour', type='primary'):
            execute('POST', '/api/mock/mode/', {'mode': new_mode}, 'Mock behavior updated.')
        st.divider()
        out, err = call('GET', '/api/outbox/')
        if err:
            st.error(err)
        else:
            events = out['events']
            render_records('Persistent notification queue', events)
            candidates = [e for e in events if e['status'] in ('RETRY', 'PENDING')]
            if candidates:
                selected = st.selectbox('Expedite an event without waiting for retry backoff',
                    [e['id'] for e in candidates],
                    format_func=lambda val: next(f'#{e["id"]} {e["event_type"]} ({e["status"]})'
                                                  for e in candidates if e['id'] == val))
                if st.button('Retry now'):
                    execute('POST', f'/api/outbox/{selected}/retry/', success='Due time moved to now.')
        if st.button('Load mock delivery receipts'):
            receipts, error = call('GET', '/api/mock/deliveries/')
            if error:
                st.error(error)
            else:
                render_records('Idempotent mock receipts', receipts['deliveries'])
        st.caption('The dispatcher must run separately: python manage.py notification_worker')

    with audit_tab:
        data, problem = call('GET', '/api/audit/')
        if problem:
            st.error(problem)
        else:
            render_records('Audited state changes', data['audit'])

with guide_tab:
    st.markdown('''### Recommended reliability demo
1. Log in as **Alex** and register. The API replies immediately with `notification: QUEUED`.
2. Log in as the **organizer**, set mock mode to `always_503`. Register as **Sam**.
3. Refresh **Notification operations**; Sam's confirmation moves to `RETRY`.
4. Set the mock back to `healthy`; click **Retry now** or wait for automatic backoff.
5. Stop Django while the worker is active and restart it. Pending MySQL outbox records remain.
6. Cancel the workshop. Every registered member receives a separate cancellation event.
7. Check mock delivery receipts; repeated HTTP delivery of the same `event_key` creates only one receipt.

Start **all four services**: MySQL, Django API, mock HTTP server, and the worker. Streamlit is the fifth process.''')
