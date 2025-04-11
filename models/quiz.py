import ollama
import json
import re

def generate_quiz(input_text, difficulty="medium", question_type="both", num_questions=5, topic=""):
    """Generate quiz questions from text input"""
    try:
        print(f"Generating quiz with: Difficulty: {difficulty}, Question type: {question_type}, Questions: {num_questions}")
        print(f"Input text length: {len(input_text)} characters")
        print(f"Topic focus: {topic if topic else 'No specific topic'}")

        # Truncate text if it's too long
        if len(input_text) > 8000:
            print(f"Truncating input text from {len(input_text)} to 8000 characters")
            input_text = input_text[:8000]
        
        # Create the system prompt
        system_prompt = "You are an expert quiz creator for educational purposes. Create quiz questions based on the provided text content."
        
        # Determine question type instructions
        question_type_instructions = ""
        if question_type == "mcq":
            question_type_instructions = "multiple-choice questions only with 4 options each"
        elif question_type == "tf":
            question_type_instructions = "true/false questions only"
        else:  # "both"
            question_type_instructions = "a balanced mix of multiple-choice (with 4 options each) and true/false questions, with approximately 50% of each type"
        
        # Add topic focus if provided
        topic_focus = ""
        if topic:
            topic_focus = f"The questions should focus specifically on the topic of '{topic}' within the content. "
        
        # Create the user prompt
        user_prompt = f"""
Create a quiz with {num_questions} {question_type_instructions} based on the following content. 
{topic_focus}
The difficulty level should be {difficulty}.

For each question, provide:
1. The question text
2. Answer choices
3. The correct answer
4. A brief explanation of why the answer is correct

Format your response as a JSON object with a 'questions' array. Each question should include 'question', 'choices', 'correct_answer', and 'explanation' fields.

Here's the content to use:
{input_text}
"""

        print("Calling Ollama...")
        response = ollama.chat(
            model="mistral:latest",
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_prompt
                }
            ]
        )
        
        # Extract the response text
        response_text = response['message']['content']
        print(f"Received response of length: {len(response_text)}")
        
        # Parse the JSON response
        quiz_data = parse_json_response(response_text)
        
        # Check for errors in parsed data
        if "error" in quiz_data:
            print(f"Error in parsed data: {quiz_data['error']}")
            return quiz_data
        
        # Ensure questions array exists and has the right structure
        if "questions" not in quiz_data or not quiz_data["questions"]:
            print("No questions found in parsed data")
            return {"error": "No questions were generated. Please try again."}
        
        # Validate and standardize each question
        valid_questions = []
        for q in quiz_data["questions"]:
            # Skip if missing required fields
            if not all(key in q for key in ["question", "choices"]):
                print(f"Skipping question missing required fields: {q}")
                continue
                
            # Ensure choices are in the right format
            if not q["choices"] or not isinstance(q["choices"], list):
                print(f"Skipping question with invalid choices: {q}")
                continue
                
            # Standardize structure
            question = {
                "question": q["question"],
                "choices": q["choices"],
                "correct_answer": q.get("correct_answer", q["choices"][0]),
                "explanation": q.get("explanation", "No explanation provided.")
            }
            
            # Add type field based on choices
            if len(q["choices"]) == 2 and "True" in q["choices"] and "False" in q["choices"]:
                question["type"] = "True/False"
            else:
                question["type"] = "MCQ"
                
            valid_questions.append(question)
            
        # Filter questions based on the requested type
        if question_type == "mcq":
            valid_questions = [q for q in valid_questions if q["type"] == "MCQ"]
        elif question_type == "tf":
            valid_questions = [q for q in valid_questions if q["type"] == "True/False"]
        elif question_type == "both":
            # Ensure we have a good mix of both types
            mcq_questions = [q for q in valid_questions if q["type"] == "MCQ"]
            tf_questions = [q for q in valid_questions if q["type"] == "True/False"]
            
            # If we don't have any of one type, generate an error
            if not mcq_questions or not tf_questions:
                print(f"Warning: Unbalanced question types - MCQ: {len(mcq_questions)}, T/F: {len(tf_questions)}")
                if not mcq_questions and not tf_questions:
                    return {"error": "No valid questions could be generated. Please try again."}
                elif not mcq_questions:
                    return {"error": "No multiple-choice questions were generated. Please try again."}
                elif not tf_questions:
                    return {"error": "No true/false questions were generated. Please try again."}
            
            # Calculate how many of each type to include
            total_questions = min(len(valid_questions), num_questions)
            mcq_count = min(len(mcq_questions), total_questions // 2 + total_questions % 2)
            tf_count = min(len(tf_questions), total_questions - mcq_count)
            
            # Adjust MCQ count if we don't have enough T/F questions
            if tf_count < total_questions - mcq_count:
                mcq_count = total_questions - tf_count
            
            # Construct the final balanced list
            valid_questions = mcq_questions[:mcq_count] + tf_questions[:tf_count]
            
            print(f"Created balanced question mix: {mcq_count} MCQ, {tf_count} T/F")
            
        # Check if we have any valid questions after filtering
        if not valid_questions:
            return {"error": f"No valid {question_type} questions could be generated. Please try again."}
            
        print(f"Successfully generated {len(valid_questions)} valid questions")
        return {"questions": valid_questions}
        
    except Exception as e:
        print(f"Error generating quiz: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"error": f"An error occurred while generating the quiz: {str(e)}"}

def process_quiz_answers(user_answers, quiz_data):
    """
    Process user's quiz answers and calculate score
    
    Args:
        user_answers: Dictionary with question indices as keys and user's answers as values
        quiz_data: Dictionary containing quiz questions and correct answers
        
    Returns:
        Dictionary with score and feedback
    """
    # Initialize results structure
    results = {
        "score": 0,
        "total": 0,
        "percentage": 0,
        "feedback": []
    }
    
    # Basic validation
    if not user_answers or not isinstance(user_answers, dict):
        return {**results, "error": "Invalid answers format"}
    
    if not quiz_data or not isinstance(quiz_data, dict):
        return {**results, "error": "Invalid quiz data format"}
    
    if "questions" not in quiz_data or not quiz_data["questions"]:
        return {**results, "error": "No questions found in quiz data"}
    
    # Set total questions
    results["total"] = len(quiz_data["questions"])
    
    # Process each question
    for question_idx, question in enumerate(quiz_data["questions"]):
        question_key = str(question_idx)
        
        # Skip if question is missing essential data
        if "question" not in question or "correct_answer" not in question:
            continue
            
        feedback_item = {
            "question": question.get("question", ""),
            "correct_answer": question.get("correct_answer", ""),
            "explanation": question.get("explanation", "No explanation provided"),
            "is_correct": False,
            "user_answer": "No answer"
        }
        
        # Check if user answered this question
        if question_key in user_answers:
            user_answer = user_answers[question_key]
            feedback_item["user_answer"] = user_answer
            
            # Compare answers (case insensitive)
            correct_answer = question.get("correct_answer", "")
            is_correct = user_answer.lower() == correct_answer.lower()
            
            if is_correct:
                results["score"] += 1
                feedback_item["is_correct"] = True
        
        # Add feedback for this question
        results["feedback"].append(feedback_item)
    
    # Calculate percentage (avoid division by zero)
    if results["total"] > 0:
        results["percentage"] = (results["score"] / results["total"]) * 100
    
    return results 

def parse_json_response(response_text):
    """Parse JSON response from LLM and handle different response formats"""
    try:
        print(f"Attempting to parse response: {response_text[:200]}...")
        
        # Find JSON content in the response (handles when model includes other text)
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```|```([\s\S]*?)```|\{[\s\S]*\}', response_text)
        if json_match:
            json_content = json_match.group(1) or json_match.group(2) or json_match.group(0)
            # Clean up the content
            json_content = json_content.strip()
            if not json_content.startswith('{'):
                json_content = '{' + json_content
            if not json_content.endswith('}'):
                json_content = json_content + '}'
            
            try:
                data = json.loads(json_content)
                print("Successfully parsed JSON data")
                return data
            except json.JSONDecodeError as e:
                print(f"JSON decode error: {str(e)}")
                # Try to fix common JSON issues
                json_content = re.sub(r',\s*}', '}', json_content)  # Remove trailing commas
                json_content = re.sub(r',\s*]', ']', json_content)  # Remove trailing commas in arrays
                try:
                    data = json.loads(json_content)
                    print("Successfully parsed JSON data after fixing format")
                    return data
                except json.JSONDecodeError:
                    pass  # Fall through to manual parsing
                    
        # If we didn't get valid JSON, try to parse questions manually
        print("Attempting manual question parsing...")
        questions = []
        
        # Look for question patterns
        question_blocks = re.findall(r'(?:Question\s*\d+:|Q\d+:|\d+\.\s*Question:|\d+\.\s*)([^\n]+)(?:\s*Options:|\s*Choices:)?([^?]*?)(?:Answer:|Correct Answer:|Explanation:|(?=Question|Q\d+:|$))', response_text, re.DOTALL)
        
        for i, (question_text, options_text) in enumerate(question_blocks):
            question = question_text.strip()
            
            # Extract options
            choices = []
            if 'True/False' in options_text or 'True or False' in options_text:
                choices = ['True', 'False']
            else:
                # Try to extract lettered options (A, B, C, D)
                option_matches = re.findall(r'(?:^|\n)\s*([A-D])[.):]\s*([^\n]+)', options_text)
                if option_matches:
                    choices = [option.strip() for _, option in option_matches]
                else:
                    # Try numbered options
                    option_matches = re.findall(r'(?:^|\n)\s*(\d+)[.):]\s*([^\n]+)', options_text)
                    if option_matches:
                        choices = [option.strip() for _, option in option_matches]
            
            # Extract correct answer and explanation if available
            answer_match = re.search(r'(?:Answer:|Correct Answer:)\s*([^\n]+)', response_text)
            explanation_match = re.search(r'(?:Explanation:)\s*([^\n]+)', response_text)
            
            correct_answer = answer_match.group(1).strip() if answer_match else ""
            explanation = explanation_match.group(1).strip() if explanation_match else "No explanation provided."
            
            questions.append({
                "question": question,
                "choices": choices,
                "correct_answer": correct_answer,
                "explanation": explanation
            })
        
        if questions:
            print(f"Manually parsed {len(questions)} questions")
            return {"questions": questions}
    
    except Exception as e:
        print(f"Error parsing response: {str(e)}")
    
    # If all parsing attempts fail, return error
    return {"error": "Could not parse quiz questions from the model's response. Please try again."} 