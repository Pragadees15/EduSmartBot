from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import os
from werkzeug.utils import secure_filename
import json
import traceback
from models.scrape import web_scrape, parse_content
from models.ocr import extract_text_from_file, process_ocr_question
from models.chatbot import get_chatbot_response
from models.quiz import generate_quiz as generate_quiz_function, process_quiz_answers
import uuid
import models.ocr

app = Flask(__name__)
app.secret_key = 'edusmart_secret_key'

# Set absolute path for uploads folder
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Create uploads folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
print(f"Upload folder path: {app.config['UPLOAD_FOLDER']}")

allowed_extensions = {'pdf', 'png', 'jpg', 'jpeg', 'txt', 'docx', 'doc'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

@app.route('/')
def index():
    # Clear all session data when returning to the home page
    session.clear()
    return render_template('index.html')

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
    results = web_scrape(query)
    return jsonify(results)

@app.route('/scrape-website', methods=['POST'])
def scrape_website():
    url = request.form.get('url')
    try:
        content = web_scrape(url, scrape_type='content')
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
    
    answer = parse_content(content, question)
    return jsonify({'answer': answer})

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
        
        # Extract text from file based on its type
        extracted_text = ""
        if file_extension in ['.pdf', '.txt', '.docx', '.doc', '.png', '.jpg', '.jpeg']:
            extracted_text = models.ocr.extract_text_from_file(file_path)
            
            # Store extracted text in session for later use
            session['extracted_text'] = extracted_text
        else:
            # Clean up the uploaded file
            os.remove(file_path)
            return jsonify({'error': 'Unsupported file type. Please upload a PDF, DOCX, TXT, PNG, JPG, or JPEG file.'}), 400
        
        # Check if text was successfully extracted
        if not extracted_text:
            return jsonify({'error': 'Could not extract text from the uploaded file.'}), 400
        
        # Return the extracted text
        return jsonify({
            'text': extracted_text,
            'filename': file.filename
        })
    
    except Exception as e:
        print(f"Error in upload_file: {str(e)}")
        return jsonify({'error': f'An error occurred: {str(e)}'}), 500

@app.route('/ask-ocr-content', methods=['POST'])
def ask_ocr_content():
    question = request.form.get('question')
    text = session.get('extracted_text', '')
    if not text:
        return jsonify({'error': 'No extracted text available'})
    
    answer = process_ocr_question(text, question)
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
    
    # Get response from chatbot
    response = get_chatbot_response(message, session['chat_history'])
    
    # Add assistant response to history
    session['chat_history'].append({'role': 'assistant', 'content': response})
    session.modified = True
    
    return jsonify({'response': response})

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
            topic=topic
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
    return jsonify({
        'session': {key: session.get(key) for key in session},
        'quiz_data_exists': 'quiz_data' in session,
        'quiz_options': session.get('quiz_options'),
        'question_count': len(session.get('quiz_data', {}).get('questions', [])) if 'quiz_data' in session else 0
    })

# Add a route to clear session data
@app.route('/debug/clear-session')
def clear_session():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    # Enable cloudflared tunnel for public URL
    #from flask_cloudflared import run_with_cloudflared
    #run_with_cloudflared(app)
    app.run(debug=True) 