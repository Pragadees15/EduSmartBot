from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from datetime import datetime, timedelta, time, timezone
import uuid
import os
from werkzeug.utils import secure_filename
import json
import traceback
import re
import urllib.request
import urllib.error
from models.scrape import web_scrape, parse_content, parse_content_with_model, intelligent_web_search, search_with_similarity
from models.ocr import extract_text_from_file, process_ocr_question, extract_text_with_metadata
from models.chatbot import get_chatbot_response, stream_chatbot_response
from models.quiz import generate_quiz as generate_quiz_function, process_quiz_answers
import models.ocr
from flask_session import Session
import tempfile

app = Flask(__name__)
# Secret key and config from environment
app.secret_key = os.environ.get('SECRET_KEY', 'edusmart_secret_key')

# Configure server-side session storage
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = os.path.join(tempfile.gettempdir(), "edusmart_sessions")
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_USE_SIGNER"] = True
app.config["SESSION_COOKIE_SECURE"] = os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() == 'true'
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = os.environ.get('SESSION_COOKIE_SAMESITE', 'Lax')
try:
    _lifetime_minutes = int(os.environ.get('SESSION_LIFETIME_MINUTES', '120'))
except Exception:
    _lifetime_minutes = 120
app.permanent_session_lifetime = timedelta(minutes=_lifetime_minutes)

# Create sessions directory if it doesn't exist
os.makedirs(app.config["SESSION_FILE_DIR"], exist_ok=True)
print(f"Session storage path: {app.config['SESSION_FILE_DIR']}")

Session(app)

# Set absolute path for uploads folder
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
DELETE_UPLOADS_AFTER_PROCESSING = os.environ.get('DELETE_UPLOADS_AFTER_PROCESSING', 'true').lower() == 'true'
ENABLE_DEBUG_ROUTES = os.environ.get('ENABLE_DEBUG_ROUTES', 'false').lower() == 'true'
CHAT_HISTORY_MAX = int(os.environ.get('CHAT_HISTORY_MAX', '25'))

# Create uploads folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
print(f"Upload folder path: {app.config['UPLOAD_FOLDER']}")

allowed_extensions = {'pdf', 'png', 'jpg', 'jpeg', 'txt', 'docx', 'doc'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

# -----------------------------
# Internationalization (i18n)
# -----------------------------

@app.context_processor
def inject_lang():
    """Inject the current language into all templates."""
    current_lang = session.get('lang', 'en')
    return {'current_lang': current_lang}


@app.route('/set-language', methods=['POST'])
def set_language():
    """Set the preferred language in the session."""
    try:
        lang = (request.json or {}).get('lang') if request.is_json else request.form.get('lang')
        if not lang:
            return jsonify({'error': 'No language provided'}), 400
        # Allow simple "xx" or "xx-YY" codes; keep simple allowlist here if needed
        session['lang'] = lang
        session.modified = True
        return jsonify({'success': True, 'lang': lang})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/')
def index():
    # Do not clear session on homepage to preserve user data across pages
    return render_template('index.html')

# Timetable routes
@app.route('/timetable')
def timetable_page():
    if 'timetable' not in session:
        session['timetable'] = []
    if 'timetable_info' not in session:
        session['timetable_info'] = {
            'subjects': '',
            'exams': '',
            'focus_areas': '',
            'study_goals': ''
        }
    # Pass current timetable to template
    days = [
        'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'
    ]
    hours = [f"{h:02d}:00" for h in range(6, 22 + 1)]
    return render_template('timetable.html', 
                         timetable=session.get('timetable', []), 
                         days=days, 
                         hours=hours,
                         timetable_info=session.get('timetable_info', {}))


def _parse_time_str(value: str):
    """Parse time string in HH:MM or HH:MM:SS format."""
    if not value:
        return None
    try:
        # Try HH:MM format first
        if len(value) == 5:
            return datetime.strptime(value, '%H:%M').time()
        # Try HH:MM:SS format
        elif len(value) == 8:
            return datetime.strptime(value, '%H:%M:%S').time()
        # Try to extract HH:MM from longer strings
        else:
            parts = value.split(':')
            if len(parts) >= 2:
                return datetime.strptime(f"{parts[0]}:{parts[1]}", '%H:%M').time()
        return None
    except Exception:
        return None


def _is_overlap(a_start: time, a_end: time, b_start: time, b_end: time) -> bool:
    # Overlap when start < other_end and end > other_start
    return (a_start < b_end) and (a_end > b_start)


def _validate_event(day: str, start: str, end: str, title: str, type_: str):
    valid_days = {'Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'}
    if day not in valid_days:
        return 'Invalid day'
    start_t = _parse_time_str(start)
    end_t = _parse_time_str(end)
    if not start_t or not end_t:
        return 'Invalid time format (use HH:MM 24-hour)'
    if not (time(6,0) <= start_t < end_t <= time(22,0)):
        return 'Time must be between 06:00 and 22:00 and start < end'
    if not title or not isinstance(title, str):
        return 'Title is required'
    if type_ not in {'class','lab','self-study'}:
        return 'Invalid type'
    return None


@app.route('/timetable/add', methods=['POST'])
def timetable_add():
    try:
        payload = request.get_json(silent=True) or request.form
        if not payload:
            return jsonify({'error': 'No data provided'}), 400
        
        day = (payload.get('day') or '').strip()
        start = (payload.get('start') or '').strip()
        end = (payload.get('end') or '').strip()
        title = (payload.get('title') or '').strip()
        type_ = (payload.get('type') or '').strip()
        
        err = _validate_event(day, start, end, title, type_)
        if err:
            return jsonify({'error': err}), 400

        start_t = _parse_time_str(start)
        end_t = _parse_time_str(end)

        if 'timetable' not in session:
            session['timetable'] = []
        # Overlap check for same day
        for ev in session['timetable']:
            if ev.get('day') == day:
                ev_start = _parse_time_str(ev.get('start',''))
                ev_end = _parse_time_str(ev.get('end',''))
                if ev_start and ev_end and _is_overlap(start_t, end_t, ev_start, ev_end):
                    return jsonify({'error': 'Time overlaps with an existing event'}), 400

        event_id = str(uuid.uuid4())
        new_event = {
            'id': event_id,
            'day': day,
            'start': start,
            'end': end,
            'title': title,
            'type': type_
        }
        session['timetable'].append(new_event)
        # Sort by day then start time for consistency
        day_order = {d:i for i,d in enumerate(['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'])}
        session['timetable'].sort(key=lambda e: (day_order.get(e.get('day'), 99), e.get('start')))
        session.modified = True
        return jsonify({'success': True, 'event': new_event, 'timetable': session['timetable']})
    except Exception as e:
        print(f"Error in timetable_add: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'An error occurred: {str(e)}'}), 500


@app.route('/timetable/update', methods=['POST'])
def timetable_update():
    """Update an existing event."""
    try:
        payload = request.get_json(silent=True) or request.form
        event_id = (payload.get('id') or '').strip()
        if not event_id:
            return jsonify({'error': 'Missing event id'}), 400
        
        day = (payload.get('day') or '').strip()
        start = (payload.get('start') or '').strip()
        end = (payload.get('end') or '').strip()
        title = (payload.get('title') or '').strip()
        type_ = (payload.get('type') or '').strip()

        err = _validate_event(day, start, end, title, type_)
        if err:
            return jsonify({'error': err}), 400

        start_t = _parse_time_str(start)
        end_t = _parse_time_str(end)

        if 'timetable' not in session:
            session['timetable'] = []
        
        # Find the event to update
        event_to_update = None
        for ev in session['timetable']:
            if str(ev.get('id')) == event_id:
                event_to_update = ev
                break
        
        if not event_to_update:
            return jsonify({'error': 'Event not found'}), 404
        
        # Check overlap with other events (excluding the event being updated)
        for ev in session['timetable']:
            if str(ev.get('id')) != event_id and ev.get('day') == day:
                ev_start = _parse_time_str(ev.get('start',''))
                ev_end = _parse_time_str(ev.get('end',''))
                if ev_start and ev_end and _is_overlap(start_t, end_t, ev_start, ev_end):
                    return jsonify({'error': 'Time overlaps with an existing event'}), 400

        # Update the event
        event_to_update['day'] = day
        event_to_update['start'] = start
        event_to_update['end'] = end
        event_to_update['title'] = title
        event_to_update['type'] = type_
        
        # Sort by day then start time
        day_order = {d:i for i,d in enumerate(['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'])}
        session['timetable'].sort(key=lambda e: (day_order.get(e.get('day'), 99), e.get('start')))
        session.modified = True
        return jsonify({'success': True, 'event': event_to_update, 'timetable': session['timetable']})
    except Exception as e:
        print(f"Error in timetable_update: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'An error occurred: {str(e)}'}), 500


@app.route('/timetable/delete', methods=['POST'])
def timetable_delete():
    payload = request.get_json(silent=True) or request.form
    event_id = (payload.get('id') or '').strip()
    if not event_id:
        return jsonify({'error': 'Missing event id'}), 400
    if 'timetable' not in session:
        session['timetable'] = []
    before = len(session['timetable'])
    session['timetable'] = [ev for ev in session['timetable'] if str(ev.get('id')) != event_id]
    after = len(session['timetable'])
    session.modified = True
    if before == after:
        return jsonify({'error': 'Event not found'}), 404
    return jsonify({'success': True, 'timetable': session['timetable']})


@app.route('/timetable/clear', methods=['POST'])
def timetable_clear():
    """Clear all events from the timetable."""
    session['timetable'] = []
    session.modified = True
    return jsonify({'success': True, 'timetable': []})


@app.route('/timetable/save-info', methods=['POST'])
def timetable_save_info():
    """Save user study information (subjects, exams, focus areas, goals)."""
    payload = request.get_json(silent=True) or request.form
    info = {
        'subjects': (payload.get('subjects') or '').strip(),
        'exams': (payload.get('exams') or '').strip(),
        'focus_areas': (payload.get('focus_areas') or '').strip(),
        'study_goals': (payload.get('study_goals') or '').strip()
    }
    session['timetable_info'] = info
    session.modified = True
    return jsonify({'success': True, 'info': info})


@app.route('/timetable/export', methods=['GET'])
def timetable_export():
    """Export timetable and study information as JSON."""
    export_data = {
        'timetable': session.get('timetable', []),
        'study_info': session.get('timetable_info', {
            'subjects': '',
            'exams': '',
            'focus_areas': '',
            'study_goals': ''
        })
    }
    from flask import Response
    return Response(
        json.dumps(export_data, indent=2),
        mimetype='application/json',
        headers={
            'Content-Disposition': 'attachment; filename=timetable_export.json'
        }
    )


def _find_free_blocks_for_day(events, start_bound=time(6,0), end_bound=time(22,0)):
    """Find free time blocks for a day, excluding ALL events (classes, labs, self-study)."""
    blocks = []
    # Collect and sort intervals - include ALL events to find truly free time
    intervals = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        s = _parse_time_str(ev.get('start', ''))
        e = _parse_time_str(ev.get('end', ''))
        if s and e:
            # Ensure times are within bounds
            if s < start_bound:
                s = start_bound
            if e > end_bound:
                e = end_bound
            if s < e:
                intervals.append((s, e))
    
    # Sort by start time
    intervals.sort(key=lambda t: t[0])
    
    # Merge overlapping intervals
    merged = []
    for s, e in intervals:
        if not merged:
            merged.append((s, e))
        else:
            last_s, last_e = merged[-1]
            if s <= last_e:  # Overlapping or adjacent
                merged[-1] = (last_s, max(e, last_e))
            else:
                merged.append((s, e))
    
    # Find gaps between merged intervals
    cursor = start_bound
    for s, e in merged:
        if s > cursor:
            # Free block found
            blocks.append((cursor, s))
        cursor = max(cursor, e)
    
    # Check if there's free time after the last event
    if cursor < end_bound:
        blocks.append((cursor, end_bound))
    
    return blocks


@app.route('/timetable/import', methods=['POST'])
def timetable_import():
    """Import timetable from JSON array replacing current session timetable.
    Expected payload: { "timetable": [ {day,start,end,title,type}... ], "study_info": {...} } or raw array.
    Also supports study_info in the JSON.
    """
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({'error': 'Invalid JSON'}), 400
    
    # Handle study_info if provided
    if isinstance(data, dict) and 'study_info' in data:
        study_info = data.get('study_info', {})
        if isinstance(study_info, dict):
            session['timetable_info'] = {
                'subjects': str(study_info.get('subjects', '')).strip(),
                'exams': str(study_info.get('exams', '')).strip(),
                'focus_areas': str(study_info.get('focus_areas', '')).strip(),
                'study_goals': str(study_info.get('study_goals', '')).strip()
            }
            session.modified = True
    
    events = data.get('timetable') if isinstance(data, dict) else data
    if not isinstance(events, list):
        return jsonify({'error': 'Expected a JSON array under key "timetable" or as root'}), 400

    # Basic validation and normalization
    normalized = []
    valid_days = {'Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'}
    for ev in events:
        if not isinstance(ev, dict):
            return jsonify({'error': 'Each event must be an object'}), 400
        day = str(ev.get('day','')).strip()
        start = str(ev.get('start','')).strip()
        end = str(ev.get('end','')).strip()
        title = str(ev.get('title','')).strip()
        type_ = str(ev.get('type','')).strip() or 'class'
        err = _validate_event(day, start, end, title, type_)
        if err:
            return jsonify({'error': f'Invalid event: {err}', 'event': ev}), 400
        normalized.append({'id': str(ev.get('id') or uuid.uuid4()), 'day': day, 'start': start, 'end': end, 'title': title, 'type': type_})

    # Overlap check per day
    by_day = {d: [] for d in valid_days}
    for ev in normalized:
        by_day[ev['day']].append(ev)
    for day, day_events in by_day.items():
        # sort by start time
        day_events.sort(key=lambda e: e['start'])
        for i in range(len(day_events)):
            for j in range(i+1, len(day_events)):
                s1 = _parse_time_str(day_events[i]['start']); e1 = _parse_time_str(day_events[i]['end'])
                s2 = _parse_time_str(day_events[j]['start']); e2 = _parse_time_str(day_events[j]['end'])
                if s1 and e1 and s2 and e2 and _is_overlap(s1, e1, s2, e2):
                    return jsonify({'error': f'Overlap detected on {day}', 'a': day_events[i], 'b': day_events[j]}), 400

    session['timetable'] = normalized
    day_order = {d:i for i,d in enumerate(['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'])}
    session['timetable'].sort(key=lambda e: (day_order.get(e.get('day'), 99), e.get('start')))
    session.modified = True
    return jsonify({
        'success': True, 
        'timetable': session['timetable'],
        'study_info': session.get('timetable_info', {})
    })


@app.route('/timetable/ai-plan', methods=['POST'])
def timetable_ai_plan():
    # Compute free blocks first - include ALL events (classes, labs, self-study) to find truly free time
    tt = session.get('timetable', [])
    by_day = {d: [] for d in ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']}
    # Include ALL events when finding free blocks (not just classes/labs)
    for ev in tt:
        if ev.get('day') in by_day:
            by_day[ev['day']].append(ev)

    free_blocks = []
    for day, events in by_day.items():
        for start, end in _find_free_blocks_for_day(events):
            # Carve into 30–45 minute study sessions
            start_dt = datetime.combine(datetime.today().date(), start)
            end_dt = datetime.combine(datetime.today().date(), end)
            cursor = start_dt
            while cursor + timedelta(minutes=30) <= end_dt:
                # Choose 45 if space allows else 30
                dur = 45 if cursor + timedelta(minutes=45) <= end_dt else 30
                block_end = cursor + timedelta(minutes=dur)
                # Avoid past 23:00 implicitly by end bound used (22:00)
                free_blocks.append({
                    'day': day,
                    'start': cursor.strftime('%H:%M'),
                    'end': block_end.strftime('%H:%M')
                })
                cursor = block_end

    # Get user-provided study information
    user_info = session.get('timetable_info', {})
    
    # Extract subjects from existing timetable events (classes, labs, self-study)
    # Keep both simplified subject names AND full event titles for better matching
    subjects = set()
    subject_to_events = {}  # Map subject to its events for context
    full_event_titles = []  # Keep all original event titles
    
    for ev in tt:
        if ev.get('title'):
            title = ev.get('title', '').strip()
            original_title = title
            full_event_titles.append(original_title)
            
            # Extract subject name from event title - be more careful
            subject_name = original_title
            
            # Remove common suffixes like "Class", "Lab", "Lecture", etc.
            for suffix in [' Class', ' Lab', ' Laboratory', ' Lecture', ' Tutorial', ' Seminar', ' Workshop', ' Session']:
                if title.endswith(suffix):
                    subject_name = title[:-len(suffix)].strip()
                    break
            
            # If we didn't find a suffix, try to extract first meaningful words
            if subject_name == original_title:
                words = original_title.split()
                # Take first 1-3 words as subject (more flexible)
                if len(words) >= 1:
                    # Prefer first 2 words, but take up to 3 if needed
                    num_words = min(3, len(words))
                    subject_name = ' '.join(words[:num_words])
                    # Remove suffixes from extracted name
                    for suffix in ['Class', 'Lab', 'Lecture', 'Tutorial', 'Seminar', 'Workshop']:
                        if subject_name.endswith(suffix):
                            subject_name = subject_name[:-len(suffix)].strip()
                            break
            
            if subject_name:
                subjects.add(subject_name)
                # Also add original title as a variant for matching
                subjects.add(original_title)
                if subject_name not in subject_to_events:
                    subject_to_events[subject_name] = []
                subject_to_events[subject_name].append(ev)
                # Also index by original title
                if original_title not in subject_to_events:
                    subject_to_events[original_title] = []
                subject_to_events[original_title].append(ev)
    
    # Also add subjects from user-provided info
    if user_info.get('subjects'):
        user_subjects = [s.strip() for s in user_info['subjects'].split(',') if s.strip()]
        for us in user_subjects:
            subjects.add(us)
            if us not in subject_to_events:
                subject_to_events[us] = []
    
    # Prepare prompt for LLM to label tasks for each block
    # Group blocks by day for better distribution
    blocks_by_day = {}
    for block in free_blocks:
        day = block['day']
        if day not in blocks_by_day:
            blocks_by_day[day] = []
        blocks_by_day[day].append(block)
    
    # Sort blocks within each day by start time to enable time diversity selection
    for day in blocks_by_day:
        blocks_by_day[day].sort(key=lambda b: b['start'])
    
    # Limit blocks per day and ensure distribution across week AND time of day
    max_per_day = 3  # Maximum suggestions per day
    total_limit = 15  # Total suggestions limit
    selected_blocks = []
    days_with_blocks = sorted([d for d in blocks_by_day.keys() if blocks_by_day[d]])
    
    # FIRST: Filter out most early morning blocks (6-8 AM) globally
    # Only keep them if they're the only option
    all_blocks_filtered = []
    early_morning_blocks = []
    for day, blocks in blocks_by_day.items():
        for block in blocks:
            hour = int(block['start'].split(':')[0])
            if 6 <= hour < 8:
                early_morning_blocks.append((day, block))
            else:
                all_blocks_filtered.append((day, block))
    
    # Only use early morning if we don't have enough other blocks
    if len(all_blocks_filtered) < total_limit:
        # Add early morning blocks only if needed, limit to 1-2 total
        early_morning_blocks.sort(key=lambda x: x[1]['start'])  # Sort by time
        needed = total_limit - len(all_blocks_filtered)
        all_blocks_filtered.extend(early_morning_blocks[:min(2, needed)])
    
    # Rebuild blocks_by_day with filtered blocks
    blocks_by_day_filtered = {d: [] for d in days_with_blocks}
    for day, block in all_blocks_filtered:
        blocks_by_day_filtered[day].append(block)
    
    days_with_blocks = [d for d in days_with_blocks if blocks_by_day_filtered[d]]
    
    # Distribute evenly across days AND time slots (morning, afternoon, evening)
    if days_with_blocks:
        blocks_per_day = max(1, min(max_per_day, total_limit // len(days_with_blocks)))
        
        # Helper function to categorize time of day
        def get_time_category(start_time):
            hour = int(start_time.split(':')[0])
            if 6 <= hour < 12:
                return 'morning'
            elif 12 <= hour < 17:
                return 'afternoon'
            else:
                return 'evening'
        
        # For each day, prioritize afternoon/evening blocks
        for day in days_with_blocks:
            day_blocks = blocks_by_day_filtered[day]
            # Separate by time category, prioritizing afternoon/evening
            blocks_by_time = {'early_morning': [], 'morning': [], 'afternoon': [], 'evening': []}
            for block in day_blocks:
                hour = int(block['start'].split(':')[0])
                if 6 <= hour < 8:
                    blocks_by_time['early_morning'].append(block)
                elif 8 <= hour < 12:
                    blocks_by_time['morning'].append(block)
                elif 12 <= hour < 17:
                    blocks_by_time['afternoon'].append(block)
                else:
                    blocks_by_time['evening'].append(block)
            
            # Prioritize: afternoon > evening > morning (8-12) > early morning (6-8)
            priority_order = ['afternoon', 'evening', 'morning', 'early_morning']
            selected_for_day = []
            
            for period in priority_order:
                if len(selected_for_day) >= blocks_per_day:
                    break
                period_blocks = blocks_by_time[period]
                if not period_blocks:
                    continue
                
                # Take from this period
                needed = blocks_per_day - len(selected_for_day)
                if len(period_blocks) > needed:
                    # Take evenly distributed samples (avoid first ones)
                    step = max(1, len(period_blocks) // (needed + 1))
                    start_idx = len(period_blocks) // 3  # Start from 1/3 into the list
                    indices = [start_idx + (i * step) for i in range(needed)]
                    indices = [i for i in indices if i < len(period_blocks)]
                    selected_for_day.extend([period_blocks[i] for i in indices])
                else:
                    selected_for_day.extend(period_blocks[:needed])
            
            selected_blocks.extend(selected_for_day[:blocks_per_day])
            
            if len(selected_blocks) >= total_limit:
                break
    
    # Use existing chat mechanism; keep a temporary isolated history
    try:
        if not selected_blocks:
            return jsonify([])
        
        # Build comprehensive context about user's EXISTING SCHEDULE
        schedule_context = ""
        subjects_list_str = ""
        if subjects:
            subjects_list_str = ", ".join(sorted(subjects))
        
        if tt:
            # Organize events by day for clear presentation
            schedule_by_day = {}
            for ev in tt:
                day = ev.get('day', '')
                if day:
                    if day not in schedule_by_day:
                        schedule_by_day[day] = []
                    schedule_by_day[day].append(ev)
            
            # Format schedule for AI understanding
            schedule_lines = []
            for day in ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']:
                if day in schedule_by_day and schedule_by_day[day]:
                    day_events = sorted(schedule_by_day[day], key=lambda x: x.get('start', ''))
                    event_strs = []
                    for ev in day_events:
                        ev_type = ev.get('type', 'event')
                        title = ev.get('title', 'Untitled')
                        start = ev.get('start', '')
                        end = ev.get('end', '')
                        event_str = f"  {start}-{end}: {title} ({ev_type})"
                        event_strs.append(event_str)
                    schedule_lines.append(f"{day}:\n" + "\n".join(event_strs))
            
            if schedule_lines:
                # Build subject-to-schedule mapping for better context
                subject_schedule_info = {}
                for day, day_events in schedule_by_day.items():
                    for ev in day_events:
                        title = ev.get('title', '').strip()
                        if title:
                            # Extract subject from title
                            subject = title
                            for suffix in [' Class', ' Lab', ' Laboratory', ' Lecture', ' Tutorial']:
                                if title.endswith(suffix):
                                    subject = title[:-len(suffix)].strip()
                                    break
                            
                            if subject not in subject_schedule_info:
                                subject_schedule_info[subject] = []
                            subject_schedule_info[subject].append({
                                'day': day,
                                'time': f"{ev.get('start', '')}-{ev.get('end', '')}",
                                'type': ev.get('type', 'event'),
                                'title': title
                            })
                
                # Format subject schedule mapping
                subject_mapping = ""
                if subject_schedule_info:
                    subject_mapping = "\n\n📚 SUBJECT SCHEDULE MAPPING (use these exact subjects and times):\n"
                    for subject, events in sorted(subject_schedule_info.items()):
                        event_list = []
                        for e in events:
                            event_list.append(f"{e['day']} {e['time']} ({e['type']})")
                        subject_mapping += f"  • {subject}: {', '.join(event_list)}\n"
                
                schedule_context = (
                    "\n\n📅 USER'S CURRENT WEEKLY SCHEDULE (existing classes, labs, and self-study):\n" +
                    "\n".join(schedule_lines) +
                    subject_mapping +
                    "\n\n⚠️ CRITICAL RULES FOR SUGGESTIONS:\n" +
                    "1. You MUST ONLY use subjects/courses that appear in the schedule above.\n" +
                    "2. Use the EXACT subject names from the schedule (e.g., if schedule shows 'Mathematics Class', you can say 'Mathematics' or 'Math').\n" +
                    "3. Make suggestions contextually relevant:\n" +
                    "   - If a class is on Monday 9 AM, suggest review/preparation on Sunday evening or Monday early morning (before 8 AM)\n" +
                    "   - If a lab is on Tuesday 2 PM, suggest practice problems on Tuesday evening (after 5 PM)\n" +
                    "   - If a class is on Wednesday, suggest review on Tuesday evening or Wednesday morning before class\n" +
                    "4. Reference specific classes in your suggestions (e.g., 'Review Mathematics: Prepare for Monday's Algebra class')\n" +
                    "5. Avoid suggesting the same subject too close to class time (maintain 2+ hour gaps)\n" +
                    "6. Balance subjects across the week based on their class frequency\n" +
                    "7. Make suggestions specific and actionable, not generic\n"
                )
            elif subjects_list_str:
                schedule_context = (
                    "\n\n📚 USER'S SUBJECTS (detected from schedule):\n" +
                    f"  {subjects_list_str}\n\n" +
                    "⚠️ CRITICAL CONSTRAINT: You MUST ONLY suggest study tasks for subjects listed above. "
                    "DO NOT invent or suggest subjects that are NOT in the user's schedule.\n\n"
                )
        
        # Build comprehensive context about user's study information
        context_parts = []
        
        # Subjects/Courses
        if subjects:
            subjects_list = sorted(list(subjects))
            context_parts.append(f"User's subjects/courses: {', '.join(subjects_list)}")
        
        # Upcoming exams
        if user_info.get('exams'):
            context_parts.append(f"Upcoming exams/deadlines: {user_info['exams']}")
        
        # Focus areas (weak topics)
        if user_info.get('focus_areas'):
            context_parts.append(f"Areas needing more focus: {user_info['focus_areas']}")
        
        # Study goals
        if user_info.get('study_goals'):
            context_parts.append(f"Study goals: {user_info['study_goals']}")
        
        # Build the context string
        if context_parts:
            user_context = "\n\n📚 ADDITIONAL USER INFORMATION:\n" + "\n".join(f"- {part}" for part in context_parts) + \
                          "\n\nUse this information to create personalized, relevant study suggestions. " \
                          "Prioritize subjects that need more focus, prepare for upcoming exams, and align with study goals. " \
                          "BUT REMEMBER: Only use subjects from the schedule above."
        else:
            user_context = "\n\nNote: No additional user information provided. Suggest study topics based on free time blocks and existing schedule. " \
                          "ONLY use subjects that appear in the user's schedule."
        
        # Combine schedule and user context
        full_context = schedule_context + user_context
        
        # Show distribution summary
        day_summary = {}
        for block in selected_blocks:
            day = block['day']
            day_summary[day] = day_summary.get(day, 0) + 1
        distribution_info = ", ".join([f"{day}: {count} blocks" for day, count in sorted(day_summary.items())])
        
        # Analyze time distribution of selected blocks
        time_distribution = {'morning': 0, 'afternoon': 0, 'evening': 0}
        for block in selected_blocks:
            hour = int(block['start'].split(':')[0])
            if 6 <= hour < 12:
                time_distribution['morning'] += 1
            elif 12 <= hour < 17:
                time_distribution['afternoon'] += 1
            else:
                time_distribution['evening'] += 1
        
        time_dist_info = ", ".join([f"{k}: {v}" for k, v in time_distribution.items() if v > 0])
        
        # Create a mapping of blocks by day+time for validation
        block_map = {}
        for block in selected_blocks:
            key = f"{block['day']}_{block['start']}_{block['end']}"
            block_map[key] = block
        
        # DETERMINISTIC APPROACH: Pre-assign subjects to blocks based on schedule
        # Simple strategy: Find the closest class to each free block and use that subject
        day_order = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
        
        # For each selected block, find the closest class and use its subject
        blocks_with_subjects = []
        for block in selected_blocks:
            block_day = block['day']
            block_day_idx = day_order.index(block_day)
            block_start = _parse_time_str(block['start'])
            
            best_event = None
            best_reason = None
            min_distance = float('inf')
            
            # Find closest class on same day
            if block_day in by_day:
                for ev in by_day[block_day]:
                    if ev.get('type') in ('class', 'lab') and ev.get('title'):
                        ev_start = _parse_time_str(ev.get('start', ''))
                        if ev_start:
                            # Calculate time distance in hours
                            if ev_start < block_start:
                                # Class before block - follow-up
                                distance = (block_start.hour * 60 + block_start.minute) - (ev_start.hour * 60 + ev_start.minute)
                                if distance < min_distance and distance > 0:
                                    min_distance = distance
                                    best_event = ev
                                    best_reason = 'follow-up'
                            elif ev_start > block_start:
                                # Class after block - preparation
                                distance = (ev_start.hour * 60 + ev_start.minute) - (block_start.hour * 60 + block_start.minute)
                                if distance < min_distance and distance > 0:
                                    min_distance = distance
                                    best_event = ev
                                    best_reason = 'prepare'
            
            # If no same-day class found, check next day
            if not best_event:
                if block_day_idx < len(day_order) - 1:
                    next_day = day_order[block_day_idx + 1]
                    if next_day in by_day:
                        for ev in by_day[next_day]:
                            if ev.get('type') in ('class', 'lab') and ev.get('title'):
                                if not best_event:
                                    best_event = ev
                                    best_reason = 'prepare'
                                    break
            
            # If still no class, check previous day
            if not best_event:
                if block_day_idx > 0:
                    prev_day = day_order[block_day_idx - 1]
                    if prev_day in by_day:
                        for ev in by_day[prev_day]:
                            if ev.get('type') in ('class', 'lab') and ev.get('title'):
                                if not best_event:
                                    best_event = ev
                                    best_reason = 'follow-up'
                                    break
            
            # Extract subject from the best event found
            assigned_subject = None
            if best_event:
                title = best_event.get('title', '').strip()
                # Use the exact title, but remove common suffixes
                assigned_subject = title
                for suffix in [' Class', ' Lab', ' Laboratory', ' Lecture', ' Tutorial', ' Seminar']:
                    if title.endswith(suffix):
                        assigned_subject = title[:-len(suffix)].strip()
                        break
                # If still long, take first 2-3 words
                if len(assigned_subject.split()) > 3:
                    words = assigned_subject.split()
                    assigned_subject = ' '.join(words[:2])
            
            # Fallback: if no class found, use subjects from schedule
            if not assigned_subject:
                # Get clean subject list (not full event titles)
                clean_subjects = [s for s in subjects if s not in full_event_titles or len(s.split()) <= 3]
                if not clean_subjects:
                    # If no clean subjects, extract from full event titles
                    for ev in tt:
                        if ev.get('type') in ('class', 'lab') and ev.get('title'):
                            title = ev.get('title', '').strip()
                            for suffix in [' Class', ' Lab', ' Laboratory', ' Lecture', ' Tutorial']:
                                if title.endswith(suffix):
                                    clean_subjects.append(title[:-len(suffix)].strip())
                                    break
                            if not clean_subjects or clean_subjects[-1] != title:
                                words = title.split()
                                if words:
                                    clean_subjects.append(' '.join(words[:2]) if len(words) >= 2 else words[0])
                
                if clean_subjects:
                    # Round-robin through subjects to ensure distribution
                    idx = len(blocks_with_subjects) % len(clean_subjects)
                    assigned_subject = clean_subjects[idx]
                elif subjects:
                    # Last resort: use any subject from set
                    subject_list = sorted(list(subjects))
                    idx = len(blocks_with_subjects) % len(subject_list)
                    assigned_subject = subject_list[idx]
            
            # Add block with assigned subject
            blocks_with_subjects.append({
                'block': block,
                'subject': assigned_subject,
                'reason': best_reason,
                'related_event': best_event
            })
        
        # Build blocks JSON with pre-assigned subjects for AI to use
        blocks_for_ai = []
        for item in blocks_with_subjects:
            block = item['block']
            subject = item['subject']
            reason = item['reason']
            related = item['related_event']
            
            block_info = {
                'day': block['day'],
                'start': block['start'],
                'end': block['end'],
                'assigned_subject': subject,
                'context': None
            }
            
            if subject and related:
                if reason == 'prepare':
                    block_info['context'] = f"Prepare for {related.get('day')}'s {related.get('title', 'class')} at {related.get('start', '')}"
                elif reason == 'follow-up':
                    block_info['context'] = f"Follow-up on today's {related.get('title', 'class')}"
            
            # Add Study Information hints to context
            study_hints = []
            if subject:
                # Check if this subject has upcoming exams
                if user_info.get('exams') and subject.lower() in user_info['exams'].lower():
                    study_hints.append("UPCOMING EXAM - prioritize exam preparation")
                # Check if this subject has focus areas
                if user_info.get('focus_areas') and subject.lower() in user_info['focus_areas'].lower():
                    study_hints.append("NEEDS FOCUS - emphasize weak areas")
                # Check study goals
                if user_info.get('study_goals'):
                    study_hints.append(f"Goal: {user_info['study_goals']}")
            
            if study_hints:
                block_info['study_info'] = " | ".join(study_hints)
            
            blocks_for_ai.append(block_info)
        
        blocks_json = json.dumps(blocks_for_ai, indent=2)
        
        # Count early morning blocks to warn AI
        early_morning_count = sum(1 for b in selected_blocks if 6 <= int(b['start'].split(':')[0]) < 8)
        time_warning = ""
        if early_morning_count > len(selected_blocks) * 0.3:
            time_warning = f"\n⚠️ WARNING: Many blocks are at 6-7 AM. Try to prioritize later times when assigning tasks. "
        
        prompt = (
            "You are an expert academic study planner. I will provide you with:\n"
            "1. The user's complete weekly schedule (classes, labs, self-study sessions)\n"
            "2. Free time blocks with PRE-ASSIGNED subjects and context\n"
            "3. Additional user study information\n\n"
            "Your task is to create specific, actionable study task descriptions for EACH free time block.\n"
            "IMPORTANT: Each block already has an assigned subject - use that subject in your task description.\n\n"
            "CRITICAL RULES (MUST FOLLOW):\n"
            "1. You MUST output a JSON array with exactly ONE suggestion per time block provided.\n"
            "2. Each suggestion MUST use the EXACT day, start, and end times from the provided blocks.\n"
            "3. ⚠️ CRITICAL: Each block has an 'assigned_subject' field - you MUST use that subject in your task.\n"
            "4. Use the 'context' field to make your task description relevant (e.g., if context says 'Prepare for Monday's class', reference that).\n"
            "5. Make task descriptions specific and actionable:\n"
            "   - Good: 'Review Mathematics: Algebra Chapter 3 - Prepare for tomorrow's class'\n"
            "   - Good: 'Practice Physics problems: Follow-up on today's Mechanics lab'\n"
            "   - Bad: 'Study Math' (too generic)\n"
            "   - Bad: 'Review' (not specific enough)\n"
            "6. For early morning blocks (6-7 AM), suggest lighter tasks like 'Review notes' or 'Quick revision'.\n"
            "7. For afternoon/evening blocks (after 12 PM), suggest intensive study tasks like 'Practice problems' or 'Complete exercises'.\n"
            "8. Reference the context provided (upcoming classes, recent labs) to make suggestions relevant.\n\n"
            "🎯 TASK GENERATION STRATEGY:\n"
            "- Use the assigned_subject field for each block - this is the subject you MUST use\n"
            "- Use the context field to make your task relevant (e.g., 'Prepare for Monday's class', 'Follow-up on today's lab')\n"
            "- ⚠️ IMPORTANT: Check the ADDITIONAL USER INFORMATION section below:\n"
            "  * If a subject has upcoming exams, prioritize it and make suggestions exam-focused (e.g., 'Review for Mathematics exam', 'Practice exam-style problems')\n"
            "  * If a subject has focus areas mentioned, emphasize those topics (e.g., if focus is 'Algebra', suggest 'Review Algebra: Quadratic Equations')\n"
            "  * If study goals are mentioned, align suggestions with those goals\n"
            "- Make tasks specific: mention topics, chapters, or exercises (e.g., 'Review Algebra Chapter 3', 'Practice Newton's Laws problems')\n"
            "- Match study intensity to time of day (light morning, intensive afternoon/evening)\n"
            "- Reference the user's schedule when making suggestions (e.g., 'Prepare for tomorrow's Mathematics class')\n\n"
            f"{full_context}\n\n"
            f"⏰ FREE TIME BLOCKS WITH PRE-ASSIGNED SUBJECTS ({len(blocks_for_ai)} blocks):\n{blocks_json}\n\n"
            f"{time_warning}\n"
            "OUTPUT FORMAT: Return ONLY a valid JSON array. Each object must have: day (string), start (string HH:MM), end (string HH:MM), task (string).\n"
            "IMPORTANT: The 'assigned_subject' field tells you which subject to use. The 'context' field tells you why (e.g., 'Prepare for Monday's class').\n"
            "The 'study_info' field (if present) contains important hints:\n"
            "- 'UPCOMING EXAM' means this subject has an exam coming up - make suggestions exam-focused\n"
            "- 'NEEDS FOCUS' means this subject needs extra attention - emphasize weak areas\n"
            "- 'Goal: ...' tells you the user's study goals - align suggestions accordingly\n\n"
            "Example output format:\n"
            "[\n"
            '  {"day":"Monday","start":"17:00","end":"17:45","task":"Review Mathematics: Algebra Chapter 3 - Prepare for tomorrow\'s class"},\n'
            '  {"day":"Tuesday","start":"19:00","end":"19:45","task":"Practice Physics: Newton\'s Laws problems - Follow-up on today\'s Mechanics lab"},\n'
            '  {"day":"Wednesday","start":"14:00","end":"14:45","task":"Study Operating Systems: Memory Management concepts - Prepare for Thursday\'s class"},\n'
            '  {"day":"Thursday","start":"16:00","end":"16:45","task":"Database Systems: Practice SQL queries - Review today\'s class material"}\n'
            "]\n\n"
            "CRITICAL REMINDERS:\n"
            "- Use the EXACT day, start, and end times from the blocks provided.\n"
            "- Use the 'assigned_subject' field - this is the subject you MUST include in your task.\n"
            "- Use the 'context' field to make your task relevant (reference upcoming/previous classes).\n"
            "- Make tasks specific: include topics, chapters, or exercise types.\n"
            "- Return exactly one suggestion per block provided."
        )
        
        print(f"DEBUG: Sending {len(selected_blocks)} blocks to AI planner")
        print(f"DEBUG: Prompt length: {len(prompt)}")
        
        # Use get_chatbot_response to get a single-shot response respecting current lang
        plan_text = get_chatbot_response(prompt, [], lang=session.get('lang','en'))
        print(f"DEBUG: AI response length: {len(plan_text)}")
        print(f"DEBUG: AI response preview: {plan_text[:200]}")
        
        suggestions = None
        try:
            # Try direct JSON parse
            suggestions = json.loads(plan_text)
        except json.JSONDecodeError as e:
            print(f"DEBUG: Direct JSON parse failed: {e}")
            # Try to extract JSON array from response
            # Look for JSON array pattern
            json_patterns = [
                r'\[[\s\S]*?\]',  # Standard array
                r'\{[\s\S]*?"day"[\s\S]*?\}',  # Single object
            ]
            for pattern in json_patterns:
                match = re.search(pattern, plan_text, re.DOTALL)
                if match:
                    try:
                        suggestions = json.loads(match.group(0))
                        if isinstance(suggestions, list):
                            break
                        elif isinstance(suggestions, dict):
                            suggestions = [suggestions]
                            break
                    except json.JSONDecodeError:
                        continue
        
        if not suggestions or not isinstance(suggestions, list):
            print(f"DEBUG: Failed to parse JSON from response. Response: {plan_text[:500]}")
            raise ValueError('LLM did not return a valid JSON array')
        # Validate structure and match to actual free blocks
        # Use pre-assigned subjects from blocks_with_subjects
        cleaned = []
        day_counts = {}
        used_blocks = set()  # Track which blocks from selected_blocks we've used
        
        # Create a mapping from block key to assigned subject and context
        block_to_assignment = {}
        for item in blocks_with_subjects:
            block = item['block']
            block_key = f"{block['day']}_{block['start']}_{block['end']}"
            block_to_assignment[block_key] = item
        
        for item in suggestions:
            if not isinstance(item, dict) or not all(k in item for k in ('day','start','end','task')):
                continue
            if item['day'] not in by_day:
                continue
            s = _parse_time_str(item['start']); e = _parse_time_str(item['end'])
            if not s or not e or not (time(6,0) <= s < e <= time(22,0)):
                continue
            
            # Try to match this suggestion to an actual free block
            block_key = f"{item['day']}_{item['start']}_{item['end']}"
            
            # Check if we have a pre-assigned subject for this block
            assignment = block_to_assignment.get(block_key)
            
            if block_key in block_map and block_key not in used_blocks:
                # Exact match found - ALWAYS use pre-assigned subject if available
                if assignment and assignment.get('subject'):
                    assigned_subject = assignment['subject']
                    related = assignment.get('related_event')
                    reason = assignment.get('reason')
                    
                    # Build contextually relevant task using pre-assigned subject
                    if related and reason == 'prepare':
                        task_text = f"Review {assigned_subject}: Prepare for {related.get('day')}'s class"
                    elif related and reason == 'follow-up':
                        task_text = f"Review {assigned_subject}: Follow-up on today's class"
                    else:
                        task_text = f"Review {assigned_subject}"
                    
                    # Check if AI's task is good and mentions the subject
                    ai_task = str(item['task']).strip()
                    ai_task_lower = ai_task.lower()
                    assigned_lower = assigned_subject.lower()
                    
                    # Check if AI task mentions the assigned subject
                    subject_words = assigned_lower.split()
                    mentions_subject = any(word in ai_task_lower for word in subject_words if len(word) > 3)
                    
                    # If AI task is good and mentions subject, use it (but ensure subject is mentioned)
                    if mentions_subject and len(ai_task) > 10:
                        task_text = ai_task
                        print(f"DEBUG: Using AI task that mentions assigned subject: {assigned_subject}")
                    else:
                        print(f"DEBUG: Using pre-assigned subject task: {assigned_subject}")
                else:
                    # No pre-assigned subject, use AI's task
                    task_text = str(item['task']).strip()
                    print(f"DEBUG: No pre-assigned subject, using AI task")
                
                cleaned.append({
                    'day': item['day'],
                    'start': item['start'],
                    'end': item['end'],
                    'task': task_text
                })
                used_blocks.add(block_key)
                day_counts[item['day']] = day_counts.get(item['day'], 0) + 1
            else:
                # Try to find a close match (same day, same start time)
                matched = False
                for block in selected_blocks:
                    block_key_check = f"{block['day']}_{block['start']}_{block['end']}"
                    if (block_key_check not in used_blocks and 
                        block['day'] == item['day'] and
                        block['start'] == item['start']):
                        
                        # ALWAYS use pre-assigned subject if available
                        assignment = block_to_assignment.get(block_key_check)
                        if assignment and assignment.get('subject'):
                            assigned_subject = assignment['subject']
                            related = assignment.get('related_event')
                            reason = assignment.get('reason')
                            if related and reason == 'prepare':
                                task_text = f"Review {assigned_subject}: Prepare for {related.get('day')}'s class"
                            elif related and reason == 'follow-up':
                                task_text = f"Review {assigned_subject}: Follow-up on today's class"
                            else:
                                task_text = f"Review {assigned_subject}"
                        else:
                            # Fallback: extract subject from block or use schedule subjects
                            clean_subjects = [s for s in subjects if s not in full_event_titles or len(s.split()) <= 3]
                            if not clean_subjects and subjects:
                                clean_subjects = sorted(list(subjects))
                            if clean_subjects:
                                idx = len(cleaned) % len(clean_subjects)
                                task_text = f"Review {clean_subjects[idx]}"
                            else:
                                # Last resort: use AI task if available
                                task_text = str(item['task']).strip() if item.get('task') else "Review course material"
                        
                        cleaned.append({
                            'day': block['day'],
                            'start': block['start'],
                            'end': block['end'],
                            'task': task_text
                        })
                        used_blocks.add(block_key_check)
                        day_counts[block['day']] = day_counts.get(block['day'], 0) + 1
                        matched = True
                        break
        
        print(f"DEBUG: Validated {len(cleaned)} suggestions from {len(suggestions)} AI responses")
        
        # Check if distribution is too concentrated (more than 60% on one day OR too many early morning)
        if cleaned:
            max_day_count = max(day_counts.values()) if day_counts else 0
            total_count = len(cleaned)
            
            # Check time distribution (count early morning 6-7 AM)
            early_morning_count = 0
            for item in cleaned:
                hour = int(item['start'].split(':')[0])
                if 6 <= hour < 8:
                    early_morning_count += 1
            
            # Check if too concentrated in one day
            day_redistribute_needed = max_day_count > 0 and (max_day_count / total_count) > 0.6 and total_count > 3
            
            # Check if too many early morning suggestions (>50%)
            time_redistribute_needed = early_morning_count > 0 and (early_morning_count / total_count) > 0.5 and total_count > 3
            
            if day_redistribute_needed or time_redistribute_needed:
                # Redistribute: prioritize diverse times and days
                redistributed = []
                day_limits = {d: 2 if d == max(day_counts.items(), key=lambda x: x[1])[0] else 3 for d in day_counts.keys()}
                day_current = {d: 0 for d in day_counts.keys()}
                time_used = {'morning': 0, 'afternoon': 0, 'evening': 0}
                
                # Helper to categorize time
                def get_time_cat(start_time):
                    hour = int(start_time.split(':')[0])
                    if 6 <= hour < 12:
                        return 'morning'
                    elif 12 <= hour < 17:
                        return 'afternoon'
                    else:
                        return 'evening'
                
                # Sort items to prioritize diversity
                sorted_items = sorted(cleaned, key=lambda x: (
                    day_current.get(x['day'], 0),  # Prefer days with fewer items
                    time_used.get(get_time_cat(x['start']), 0)  # Prefer time periods with fewer items
                ))
                
                for item in sorted_items:
                    day = item['day']
                    time_cat = get_time_cat(item['start'])
                    
                    # Skip if day limit reached or too many early morning
                    if day_current[day] >= day_limits[day]:
                        continue
                    if time_redistribute_needed and time_cat == 'morning' and int(item['start'].split(':')[0]) < 8:
                        if time_used['morning'] >= 2:  # Limit early morning to 2
                            continue
                    
                    redistributed.append(item)
                    day_current[day] += 1
                    time_used[time_cat] += 1
                    
                    if len(redistributed) >= min(total_count, 10):  # Limit redistributed
                        break
                
                cleaned = redistributed
        
        # If we got fewer suggestions than blocks, fill remaining with smart fallbacks
        if len(cleaned) < len(selected_blocks) and len(cleaned) > 0:
            # Fill remaining blocks using pre-assigned subjects
            remaining_blocks = [b for b in selected_blocks 
                              if f"{b['day']}_{b['start']}_{b['end']}" not in used_blocks]
            if remaining_blocks:
                # Distribute remaining across days
                days_needing_more = {}
                for b in remaining_blocks:
                    if b['day'] not in days_needing_more:
                        days_needing_more[b['day']] = []
                    days_needing_more[b['day']].append(b)
                
                # Add up to 2 more per day to maintain distribution
                for day, blocks in days_needing_more.items():
                    for block in blocks[:2]:
                        if len(cleaned) < len(selected_blocks) and len(cleaned) < 15:
                            # Get pre-assigned subject for this block
                            block_key = f"{block['day']}_{block['start']}_{block['end']}"
                            assignment = block_to_assignment.get(block_key)
                            
                            if assignment and assignment.get('subject'):
                                # Use pre-assigned subject
                                assigned_subject = assignment['subject']
                                related = assignment.get('related_event')
                                reason = assignment.get('reason')
                                if related and reason == 'prepare':
                                    task = f"Review {assigned_subject}: Prepare for {related.get('day')}'s class"
                                elif related and reason == 'follow-up':
                                    task = f"Review {assigned_subject}: Follow-up on today's class"
                                else:
                                    task = f"Review {assigned_subject}"
                            else:
                                # Fallback: use subjects from schedule
                                clean_subjects = [s for s in subjects if s not in full_event_titles or len(s.split()) <= 3]
                                if not clean_subjects and subjects:
                                    clean_subjects = sorted(list(subjects))
                                if clean_subjects:
                                    idx = len(cleaned) % len(clean_subjects)
                                    task = f"Review {clean_subjects[idx]}"
                                else:
                                    task = "Review course material"
                            
                            cleaned.append({**block, 'task': task})
                            day_counts[day] = day_counts.get(day, 0) + 1
        
        if not cleaned:
            # Complete fallback: use pre-assigned subjects from blocks_with_subjects
            cleaned = []
            days_used = {}
            
            for item in blocks_with_subjects[:12]:
                block = item['block']
                day = block['day']
                day_count = days_used.get(day, 0)
                
                if day_count < 3:  # Max 3 per day
                    assigned_subject = item.get('subject')
                    related = item.get('related_event')
                    reason = item.get('reason')
                    
                    if assigned_subject:
                        if related and reason == 'prepare':
                            task = f"Review {assigned_subject}: Prepare for {related.get('day')}'s class"
                        elif related and reason == 'follow-up':
                            task = f"Review {assigned_subject}: Follow-up on today's class"
                        else:
                            task = f"Review {assigned_subject}"
                    else:
                        # Last resort: get any subject from schedule
                        clean_subjects = [s for s in subjects if s not in full_event_titles or len(s.split()) <= 3]
                        if not clean_subjects and subjects:
                            clean_subjects = sorted(list(subjects))
                        if clean_subjects:
                            idx = len(cleaned) % len(clean_subjects)
                            task = f"Review {clean_subjects[idx]}"
                        else:
                            task = "Review course material"
                    
                    cleaned.append({**block, 'task': task})
                    days_used[day] = day_count + 1
                    
                if len(cleaned) >= 10:
                    break
        
        print(f"DEBUG: Final cleaned suggestions: {len(cleaned)}")
        return jsonify(cleaned)
    except Exception as e:
        print(f"DEBUG: Exception in AI planner: {e}")
        import traceback
        traceback.print_exc()
        # Robust fallback - use pre-assigned subjects from blocks_with_subjects
        fallback = []
        days_used = {}
        
        # Get clean subjects list
        clean_subjects = [s for s in subjects if s not in full_event_titles or len(s.split()) <= 3]
        if not clean_subjects and subjects:
            clean_subjects = sorted(list(subjects))
        
        for item in blocks_with_subjects[:10]:
            block = item['block']
            day = block['day']
            
            if day not in days_used or days_used[day] < 3:
                assigned_subject = item.get('subject')
                if assigned_subject:
                    task = f"Review {assigned_subject}"
                elif clean_subjects:
                    idx = len(fallback) % len(clean_subjects)
                    task = f"Review {clean_subjects[idx]}"
                else:
                    task = "Review course material"
                    
                fallback.append({**block, 'task': task})
                days_used[day] = days_used.get(day, 0) + 1
                
            if len(fallback) >= 8:
                break
        return jsonify(fallback)

# Web Scraper routes
@app.route('/web-scraper')
def web_scraper():
    # Clear related session data on page refresh
    if 'scraped_content' in session:
        session.pop('scraped_content')
    return render_template('web_scraper.html')

@app.route('/search-web', methods=['POST'])
def search_web():
    query = request.form.get('query')
    # Optional per-request toggle to include image OCR/vision during search fetches
    include_images_flag = (request.form.get('include_images') or '').strip().lower()
    include_images = include_images_flag in ('1', 'true', 'yes', 'on')
    # Use similarity-based ranking for normal search, passing the include_images hint
    results = search_with_similarity(query, include_images=include_images)
    return jsonify(results)

@app.route('/intelligent-web-search', methods=['POST'])
def intelligent_web_search_route():
    # Accept form-encoded, JSON, or query-string
    query = None
    try:
        if request.is_json:
            payload = request.get_json(silent=True) or {}
            query = (payload.get('query') or payload.get('q'))
        if not query:
            query = request.form.get('query') or request.form.get('q')
        if not query:
            query = request.args.get('query') or request.args.get('q')
        query = (query or '').strip()
    except Exception:
        query = ''
    if not query:
        return jsonify({'error': 'No query provided'}), 400
    lang = session.get('lang', 'en')
    # Optional per-request toggle to include image OCR/vision during search fetches
    include_images_flag = ''
    try:
        if request.is_json:
            payload = request.get_json(silent=True) or {}
            include_images_flag = (str(payload.get('include_images') or '')).strip().lower()
        if not include_images_flag:
            include_images_flag = (request.form.get('include_images') or '').strip().lower()
        if not include_images_flag:
            include_images_flag = (request.args.get('include_images') or '').strip().lower()
    except Exception:
        include_images_flag = ''
    include_images = include_images_flag in ('1', 'true', 'yes', 'on')

    res = intelligent_web_search(query, max_results=5, lang=lang, include_images=include_images)
    return jsonify(res)

@app.route('/scrape-website', methods=['POST'])
def scrape_website():
    url = request.form.get('url')
    # Optional per-request toggle to include image OCR/vision
    include_images_flag = (request.form.get('include_images') or '').strip().lower()
    include_images = include_images_flag in ('1', 'true', 'yes', 'on')
    try:
        # Pass include_images explicitly to scraper instead of mutating env
        content = web_scrape(url, scrape_type='content', include_images=include_images)
        # Optionally include a hint in response when image vision was used
        # Store in session for later use
        session['scraped_content'] = content
        return jsonify({
            'success': True, 
            'content': content,
            'length': len(content)
        })
    except Exception as e:
        print(f"Error in scrape_website: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/ask-scraped-content', methods=['POST'])
def ask_scraped_content():
    question = request.form.get('question')
    content = session.get('scraped_content', '')
    if not content:
        return jsonify({'error': 'No content available. Please scrape a website first.'})
    
    res = parse_content_with_model(content, question, lang=session.get('lang', 'en'))
    return jsonify({'answer': res.get('answer'), 'modelUsed': res.get('model')})

# OCR routes
@app.route('/ocr')
def ocr():
    # Only clear session data if explicitly requested via query parameter
    if request.args.get('clear') == 'true':
        if 'extracted_text' in session:
            session.pop('extracted_text')
    return render_template('ocr.html')

@app.route('/upload-file', methods=['POST'])
def upload_file():
    try:
        # Check if file was uploaded
        if 'file' not in request.files:
            return jsonify({'error': 'No file part in the request'}), 400
        
        file = request.files['file']
        
        # Check if file is empty
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # Create uploads directory if it doesn't exist
        if not os.path.exists(app.config['UPLOAD_FOLDER']):
            os.makedirs(app.config['UPLOAD_FOLDER'])
        
        # Get file extension
        _, file_extension = os.path.splitext(file.filename)
        file_extension = file_extension.lower()
        
        # Generate unique filename
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        
        # Save file
        file.save(file_path)
        
        # Extract text with metadata based on mode
        extracted_text = ""
        result_meta = {}
        if file_extension in ['.pdf', '.txt', '.docx', '.doc', '.png', '.jpg', '.jpeg']:
            # Read optional mode from form-data
            mode = (request.form.get('mode') or 'auto').strip().lower()
            res = extract_text_with_metadata(file_path, mode=mode)
            extracted_text = res.get('text') or ''
            result_meta = res.get('meta') or {}
            # Store extracted text in session for later use
            session['extracted_text'] = extracted_text
            session.modified = True
        else:
            # Clean up the uploaded file
            os.remove(file_path)
            return jsonify({'error': 'Unsupported file type. Please upload a PDF, DOCX, TXT, PNG, JPG, or JPEG file.'}), 400
        
        # Check if text was successfully extracted
        if not extracted_text:
            return jsonify({'error': 'Could not extract text from the uploaded file.', 'meta': result_meta}), 400
        
        # Return the extracted text
        return jsonify({
            'text': extracted_text,
            'filename': file.filename,
            'meta': result_meta
        })
    
    except Exception as e:
        print(f"Error in upload_file: {str(e)}")
        return jsonify({'error': f'An error occurred: {str(e)}'}), 500
    finally:
        # Best-effort cleanup of uploaded file if enabled
        try:
            if DELETE_UPLOADS_AFTER_PROCESSING and 'file_path' in locals() and os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass

@app.route('/ask-ocr-content', methods=['POST'])
def ask_ocr_content():
    question = request.form.get('question')
    text = session.get('extracted_text', '')
    print(f"DEBUG - Session extracted_text length: {len(text) if text else 0}")
    
    if not text:
        print("DEBUG - No extracted text available in session")
        return jsonify({'error': 'No extracted text available'})
    
    answer = process_ocr_question(text, question, lang=session.get('lang', 'en'))
    return jsonify({'answer': answer})

# Chatbot routes
@app.route('/chatbot')
def chatbot():
    # Reset chat history on page refresh
    session['chat_history'] = []
    return render_template('chatbot.html', chat_history=[])

@app.route('/chat', methods=['POST'])
def chat_message():
    message = request.form.get('message')
    if not message:
        return jsonify({'error': 'No message provided'})
    
    # Add user message to history
    if 'chat_history' not in session:
        session['chat_history'] = []
    
    session['chat_history'].append({'role': 'user', 'content': message})
    # Cap chat history length
    if len(session['chat_history']) > CHAT_HISTORY_MAX:
        session['chat_history'] = session['chat_history'][-CHAT_HISTORY_MAX:]
    
    # Get response from chatbot (respect current language)
    response = get_chatbot_response(message, session['chat_history'], lang=session.get('lang', 'en'))
    
    # Add assistant response to history
    session['chat_history'].append({'role': 'assistant', 'content': response})
    if len(session['chat_history']) > CHAT_HISTORY_MAX:
        session['chat_history'] = session['chat_history'][-CHAT_HISTORY_MAX:]
    session.modified = True
    
    return jsonify({'response': response})


@app.route('/chat-stream', methods=['GET', 'POST'])
def chat_message_stream():
    """Stream chatbot response to the client as Server-Sent Events (SSE)."""
    user_message = request.form.get('message') or (request.json or {}).get('message') if request.is_json else request.args.get('message')
    if not user_message:
        return jsonify({'error': 'No message provided'}), 400

    if 'chat_history' not in session:
        session['chat_history'] = []

    # Append user message first
    session['chat_history'].append({'role': 'user', 'content': user_message})
    if len(session['chat_history']) > CHAT_HISTORY_MAX:
        session['chat_history'] = session['chat_history'][-CHAT_HISTORY_MAX:]
    session.modified = True

    from flask import stream_with_context

    @stream_with_context
    def generate():
        accumulated = []
        for chunk in stream_chatbot_response(user_message, session.get('chat_history', []), lang=session.get('lang', 'en')):
            # Send each chunk as SSE data line
            yield f"data: {json.dumps(chunk)}\n\n"
            accumulated.append(chunk)

        # At end, store assistant message in session
        assistant_text = ''.join(accumulated)
        session['chat_history'].append({'role': 'assistant', 'content': assistant_text})
        if len(session['chat_history']) > CHAT_HISTORY_MAX:
            session['chat_history'] = session['chat_history'][-CHAT_HISTORY_MAX:]
        session.modified = True
        # Signal completion
        yield "event: done\n" + f"data: {json.dumps({'done': True})}\n\n"

    from flask import Response
    headers = {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
        'Connection': 'keep-alive',
    }
    return Response(generate(), headers=headers)

# Quiz routes
@app.route('/quiz')
def quiz():
    # Reset quiz data on page refresh
    if 'quiz_data' in session:
        print(f"Clearing quiz data from session on quiz page load")
        session.pop('quiz_data', None)
    
    print(f"Rendering quiz template")
    return render_template('quiz.html')

@app.route('/generate-quiz', methods=['POST'])
def generate_quiz():
    try:
        print("Generate quiz endpoint called")
        # Get data from request
        data = request.json
        
        # Check if we have text content
        if 'text' not in data or not data['text']:
            return jsonify({'error': 'No text content provided for quiz generation'}), 400
        
        text_content = data['text']
        topic = data.get('topic', '')
        difficulty = data.get('difficulty', 'medium')
        question_type = data.get('question_type', 'both')
        
        # Map difficulty to number of questions
        question_count = {
            'easy': 5,
            'medium': 7,
            'hard': 10
        }.get(difficulty, 7)
        
        print(f"Generating quiz with: Topic: {topic}, Difficulty: {difficulty}, Question type: {question_type}, Content length: {len(text_content)}")
        
        # Generate quiz questions
        quiz_data = generate_quiz_function(
            text_content,
            difficulty=difficulty,
            question_type=question_type,
            num_questions=question_count,
            topic=topic,
            lang=session.get('lang', 'en')
        )
        
        # Check if quiz generation was successful
        if 'error' in quiz_data:
            print(f"Quiz generation failed: {quiz_data['error']}")
            return jsonify(quiz_data), 400
        
        # Store quiz in session
        session['quiz_data'] = quiz_data
        
        # Add topic to response if provided
        if topic:
            quiz_data['topic'] = topic
        
        # Return the quiz data
        return jsonify(quiz_data)
    
    except Exception as e:
        print(f"Error in generate_quiz: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f'An error occurred: {str(e)}'}), 500

@app.route('/submit-quiz', methods=['POST'])
def submit_quiz():
    try:
        print("Processing quiz submission...")
        
        # Get user answers and quiz data
        request_data = request.get_json()
        if not request_data or 'answers' not in request_data:
            print("Error: No answers provided in request")
            return jsonify({'error': 'No answers provided', 'score': 0, 'total': 0, 'percentage': 0, 'feedback': []})
        
        answers = request_data.get('answers', {})
        print(f"Received answers for {len(answers)} questions")
        
        quiz_data = session.get('quiz_data', {})
        
        if not quiz_data or 'questions' not in quiz_data:
            print("Error: No quiz data available in session")
            print(f"Session keys: {list(session.keys())}")
            return jsonify({'error': 'No quiz data available. Please generate a new quiz.', 'score': 0, 'total': 0, 'percentage': 0, 'feedback': []})
        
        question_count = len(quiz_data.get('questions', []))
        print(f"Processing answers for {question_count} questions")
        
        # Process answers and get results
        results = process_quiz_answers(answers, quiz_data)
        
        # Log result for debugging
        print(f"Quiz results: Score {results.get('score', 0)}/{results.get('total', 0)} ({results.get('percentage', 0)}%)")
        
        return jsonify(results)
    except Exception as e:
        print(f"Error processing quiz answers: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': f'Error processing quiz answers: {str(e)}', 'score': 0, 'total': 0, 'percentage': 0, 'feedback': []})

@app.route('/reset-quiz', methods=['POST'])
def reset_quiz():
    """Clear quiz data from session"""
    try:
        # Clear quiz-related session data
        if 'quiz_data' in session:
            session.pop('quiz_data')
        
        # Return success response
        return jsonify({'success': True, 'message': 'Quiz data cleared'})
    except Exception as e:
        print(f"Error in reset_quiz: {str(e)}")
        return jsonify({'error': f'An error occurred: {str(e)}'}), 500

@app.after_request
def add_cache_control(response):
    """
    Add cache control headers to prevent caching of dynamic content
    """
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, public, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# Add a debug route to view session data
@app.route('/debug/session')
def debug_session():
    if not ENABLE_DEBUG_ROUTES:
        return jsonify({'error': 'Not found'}), 404
    return jsonify({
        'session': {key: session.get(key) for key in session},
        'quiz_data_exists': 'quiz_data' in session,
        'quiz_options': session.get('quiz_options'),
        'question_count': len(session.get('quiz_data', {}).get('questions', [])) if 'quiz_data' in session else 0
    })

# Add a route to clear session data
@app.route('/debug/clear-session')
def clear_session():
    if not ENABLE_DEBUG_ROUTES:
        return jsonify({'error': 'Not found'}), 404
    session.clear()
    return redirect(url_for('index'))

@app.route('/debug/session-test')
def test_session():
    if not ENABLE_DEBUG_ROUTES:
        return jsonify({'error': 'Not found'}), 404
    # Set a value in the session
    session['test_value'] = 'This is a test'
    session.modified = True
    return jsonify({
        'message': 'Test value set in session. Visit /debug/session to see all session data.',
        'success': True
    })

if __name__ == '__main__':
    # Optionally enable cloudflared tunnel for public URL
    use_cloudflared = os.environ.get('USE_CLOUDFLARED', 'false').lower() == 'true'
    if use_cloudflared:
        try:
            from flask_cloudflared import run_with_cloudflared
            run_with_cloudflared(app)
        except Exception as e:
            print(f"Cloudflared unavailable or failed to start: {e}. Starting without tunnel...")
    app.run(debug=True)