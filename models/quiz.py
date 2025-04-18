import ollama
import json
import re
import random

def generate_quiz(input_text, difficulty="medium", question_type="both", num_questions=5, topic=""):
    """Generate quiz questions from text input"""
    try:
        print(f"Generating quiz with: Difficulty: {difficulty}, Question type: {question_type}, Questions: {num_questions}")
        print(f"Input text length: {len(input_text)} characters")
        print(f"Topic focus: {topic if topic else 'No specific topic'}")

        # Check if input text is too short
        if len(input_text) < 100:
            print(f"Warning: Input text is very short ({len(input_text)} characters)")
            return {"error": "The provided content is too short to generate meaningful quiz questions. Please provide more substantial text content."}
            
        # Truncate text if it's too long
        if len(input_text) > 8000:
            print(f"Truncating input text from {len(input_text)} to 8000 characters")
            input_text = input_text[:8000]
        
        # Create the system prompt
        system_prompt = f"""You are a quiz question generator.
DO NOT ASK TO CREATE QUESTIONS. DIRECTLY GENERATE ACTUAL QUIZ QUESTIONS.

Your task is to generate {num_questions} quiz questions and answers about the provided content.
Your response must be a valid JSON object with a 'questions' array containing multiple real questions.

IMPORTANT INSTRUCTIONS FOR MISTRAL:
1. DO NOT return a meta-question asking to create questions. Create the actual questions yourself.
2. Generate exactly {num_questions} questions in JSON format.
3. Approximately half should be multiple-choice questions and half should be true/false questions.
4. Each question must have these fields: 'question', 'choices', 'correct_answer', and 'explanation'.
5. The 'choices' field must be an array of strings.
6. For multiple-choice questions, include 4 options in the choices array.
7. For true/false questions, use ["True", "False"] as the choices array.
8. Format your output as a single JSON object without any surrounding text."""
        
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
        
        # Create the user prompt with JSON example
        user_prompt = f"""
Create a quiz with {num_questions} {question_type_instructions} based on the following content. 
{topic_focus}
The difficulty level should be {difficulty}.

IMPORTANT: Generate MULTIPLE questions (at least {num_questions}) in the format shown below.

Return your response as a valid JSON object with a 'questions' array containing multiple questions.
Here's the exact format to follow:

{{
  "questions": [
    {{
      "question": "What is the capital of France?",
      "choices": ["London", "Paris", "Berlin", "Madrid"],
      "correct_answer": "Paris",
      "explanation": "Paris is the capital city of France."
    }},
    {{
      "question": "The Earth is flat?",
      "choices": ["True", "False"],
      "correct_answer": "False",
      "explanation": "The Earth is an oblate spheroid."
    }},
    {{
      "question": "Which programming language is known for its use in machine learning?",
      "choices": ["HTML", "CSS", "Python", "JavaScript"],
      "correct_answer": "Python",
      "explanation": "Python has extensive libraries like TensorFlow and PyTorch for machine learning."
    }}
  ]
}}

CRITICAL: Your response MUST:
1. Contain a 'questions' array with multiple questions (at least {num_questions})
2. Each question must have the exact fields shown above
3. Start your response with {{ and end with }} without any additional text
4. Ensure each question has proper choices and a correct answer

Here's the content to use:
{input_text}
"""

        print("Calling Ollama with Mistral model...")
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
        
        # Check if we got a single question structure instead of questions array
        if "questions" not in quiz_data:
            print("Received non-standard format, attempting to convert")
            
            # Case 1: Response contains an 'answers' array with actual questions
            if "answers" in quiz_data and isinstance(quiz_data["answers"], list):
                print("Found 'answers' array containing questions - converting format")
                standardized_questions = []
                
                for answer in quiz_data["answers"]:
                    if isinstance(answer, dict):
                        # Handle Mistral's question-in-answer format
                        if "question" in answer:
                            std_q = {
                                "question": answer.get("question", ""),
                                "explanation": answer.get("explanation", "")
                            }
                            
                            # Handle choices/options
                            if "choices" in answer:
                                std_q["choices"] = answer["choices"]
                            elif "options" in answer:
                                std_q["options"] = answer["options"]
                            else:
                                # Default to generic options
                                std_q["choices"] = ["A", "B", "C", "D"]
                            
                            # Handle correct answer
                            if "correct_answer" in answer:
                                std_q["correct_answer"] = answer["correct_answer"]
                            elif "answer" in answer:
                                if isinstance(answer["answer"], list):
                                    std_q["correct_answer"] = answer["answer"][0] if answer["answer"] else std_q["choices"][0]
                                else:
                                    std_q["correct_answer"] = str(answer["answer"])
                            elif "correct_option" in answer:
                                std_q["correct_answer"] = answer["correct_option"]
                            else:
                                std_q["correct_answer"] = std_q["choices"][0]
                            
                            standardized_questions.append(std_q)
                        # Also handle answer object with 'qu' (truncated question)
                        elif "qu" in answer:
                            std_q = {
                                "question": answer.get("qu", ""),
                                "explanation": answer.get("explanation", "")
                            }
                            
                            # Handle options/choices
                            if "options" in answer:
                                std_q["choices"] = answer["options"]
                            elif "choices" in answer:
                                std_q["choices"] = answer["choices"]
                            else:
                                std_q["choices"] = ["A", "B", "C", "D"]
                            
                            # Handle answer
                            if "answer" in answer:
                                std_q["correct_answer"] = answer["answer"]
                            elif "correct" in answer:
                                std_q["correct_answer"] = answer["correct"]
                            else:
                                std_q["correct_answer"] = std_q["choices"][0]
                            
                            standardized_questions.append(std_q)
                
                if standardized_questions:
                    quiz_data = {"questions": standardized_questions}
                else:
                    # If couldn't extract from answers, try case 2
                    pass
            
            # Case 2: Single question format with question field
            if "questions" not in quiz_data and "question" in quiz_data:
                print("Converting single question format to questions array format")
                # Convert single question to questions array format
                single_question = {
                    "question": quiz_data.get("question", ""),
                    "explanation": quiz_data.get("explanation", "")
                }
                
                # Handle different answer formats
                if "answer" in quiz_data:
                    answer = quiz_data["answer"]
                    if isinstance(answer, list):
                        single_question["choices"] = answer
                        single_question["correct_answer"] = answer[0] if answer else ""
                    else:
                        # If answer is a string, create choices with correct answer and some wrong options
                        correct = str(answer)
                        single_question["choices"] = [correct, "Not mentioned in the text", "Cannot be determined", "None of the above"]
                        single_question["correct_answer"] = correct
                elif "options" in quiz_data and "correct_option" in quiz_data:
                    single_question["choices"] = quiz_data["options"]
                    single_question["correct_answer"] = quiz_data["correct_option"]
                else:
                    # Default options if nothing is provided
                    single_question["choices"] = ["Option A", "Option B", "Option C", "Option D"]
                    single_question["correct_answer"] = "Option A"
                
                # Replace the quiz data with our reformatted structure
                quiz_data = {"questions": [single_question]}
            
            # Case 3: Array of non-standard questions
            elif isinstance(quiz_data, list) and len(quiz_data) > 0:
                print("Converting array of questions to standard format")
                standardized_questions = []
                
                for q in quiz_data:
                    if isinstance(q, dict) and "question" in q:
                        std_q = {
                            "question": q.get("question", ""),
                            "explanation": q.get("explanation", q.get("feedback", "No explanation provided"))
                        }
                        
                        # Handle various options/choices formats
                        if "choices" in q:
                            std_q["choices"] = q["choices"]
                        elif "options" in q:
                            std_q["choices"] = q["options"]
                        else:
                            std_q["choices"] = ["A", "B", "C", "D"]
                        
                        # Handle various correct answer formats
                        if "correct_answer" in q:
                            std_q["correct_answer"] = q["correct_answer"]
                        elif "answer" in q:
                            if isinstance(q["answer"], list):
                                std_q["correct_answer"] = q["answer"][0] if q["answer"] else std_q["choices"][0]
                            else:
                                std_q["correct_answer"] = str(q["answer"])
                        elif "correct_option" in q:
                            std_q["correct_answer"] = q["correct_option"]
                        else:
                            std_q["correct_answer"] = std_q["choices"][0]
                        
                        standardized_questions.append(std_q)
                
                if standardized_questions:
                    quiz_data = {"questions": standardized_questions}
                else:
                    quiz_data = {"error": "Could not convert questions to standard format"}
            
            print("Converted to standard format:", quiz_data)
        
        # Check for errors in parsed data
        if "error" in quiz_data:
            print(f"Error in parsed data: {quiz_data['error']}")
            return quiz_data
        
        # Ensure questions array exists and has the right structure
        if "questions" not in quiz_data or not quiz_data["questions"]:
            print("No questions found in parsed data")
            return {"error": "No questions were generated. Please try again with more content."}
        
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
                "explanation": q.get("explanation", "No explanation provided.")
            }
            
            # Ensure correct_answer is a string, not a list
            if "correct_answer" in q:
                correct_answer = q["correct_answer"]
                # If correct_answer is a list, take the first item
                if isinstance(correct_answer, list):
                    correct_answer = correct_answer[0] if correct_answer else q["choices"][0]
                question["correct_answer"] = correct_answer
            else:
                question["correct_answer"] = q["choices"][0]
            
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
            if not mcq_questions and not tf_questions:
                return {"error": "No valid questions could be generated. Please try again."}
            elif not mcq_questions:
                return {"error": "No multiple-choice questions were generated. Please try again."}
            elif not tf_questions and question_type == "both":
                print("No true/false questions found, generating some from MCQs")
                # Generate true/false questions based on MCQ content
                for i, mcq in enumerate(mcq_questions[:min(3, len(mcq_questions))]):
                    # Only convert the first few MCQs to T/F to maintain balance
                    question_text = mcq["question"]
                    correct_answer = mcq["correct_answer"]
                    
                    # Create a T/F statement based on the MCQ
                    tf_statement = f"{question_text.strip('?')} is {correct_answer}."
                    
                    # Randomly decide if this should be true or false
                    is_true = random.choice([True, False])
                    
                    if is_true:
                        tf_question = {
                            "question": tf_statement,
                            "choices": ["True", "False"],
                            "correct_answer": "True",
                            "explanation": mcq["explanation"],
                            "type": "True/False"
                        }
                    else:
                        # Use a different choice for false statements
                        other_choices = [c for c in mcq["choices"] if c != correct_answer]
                        alternative = random.choice(other_choices) if other_choices else "something else"
                        tf_statement = f"{question_text.strip('?')} is {alternative}."
                        
                        tf_question = {
                            "question": tf_statement,
                            "choices": ["True", "False"],
                            "correct_answer": "False",
                            "explanation": mcq["explanation"],
                            "type": "True/False"
                        }
                        
                    tf_questions.append(tf_question)
                
                print(f"Auto-generated {len(tf_questions)} True/False questions")
                
                if not tf_questions:
                    # If we still couldn't generate any, just use MCQs
                    valid_questions = mcq_questions
                    print("Using only MCQ questions despite requesting both types")
                    return {"questions": valid_questions[:num_questions]}
            
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
            
            # Get correct answer
            correct_answer = question.get("correct_answer", "")
            
            # Compare answers (case insensitive)
            # Handle case where correct_answer is a list
            if isinstance(correct_answer, list):
                # If correct_answer is a list, convert it to a string for comparison
                correct_answer_str = str(correct_answer[0]) if correct_answer else ""
                is_correct = user_answer.lower() == correct_answer_str.lower()
                # Update feedback item with the string version
                feedback_item["correct_answer"] = correct_answer_str
            else:
                # Normal string comparison
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
        
        # Check if response looks like code instead of JSON
        if "```python" in response_text or "def " in response_text or "import " in response_text:
            print("Response appears to be code instead of JSON. Attempting to find any JSON structure.")
            # Try to find JSON content in a code response
            json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response_text)
            if not json_match:
                print("No JSON found in code response")
                return {"error": "Model returned code instead of a quiz. Please try using content with fewer code examples or more educational text."}
        
        # Find JSON content in the response (handles when model includes other text)
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```|```([\s\S]*?)```|\{[\s\S]*\}|\[[\s\S]*\]', response_text)
        if json_match:
            json_content = json_match.group(1) or json_match.group(2) or json_match.group(0)
            # Clean up the content
            json_content = json_content.strip()
            
            # Handle direct array of questions
            if json_content.startswith('[') and json_content.endswith(']'):
                print("Found an array of questions, wrapping in questions object")
                json_content = '{"questions": ' + json_content + '}'
            elif not json_content.startswith('{'):
                json_content = '{' + json_content
            if not json_content.endswith('}'):
                json_content = json_content + '}'
            
            # Remove any markdown code block markers
            json_content = re.sub(r'^```json|^```|```$', '', json_content).strip()
            
            # Fix common Mistral JSON formatting issues
            # Replace single quotes with double quotes for JSON properties
            json_content = re.sub(r"'([^']*)':", r'"\1":', json_content)
            # Replace single quotes around string values with double quotes
            json_content = re.sub(r': *\'([^\']*)\'', r': "\1"', json_content)
            
            try:
                data = json.loads(json_content)
                print("Successfully parsed JSON data")
                return data
            except json.JSONDecodeError as e:
                print(f"JSON decode error: {str(e)}")
                # Try to fix common JSON issues
                json_content = re.sub(r',\s*}', '}', json_content)  # Remove trailing commas
                json_content = re.sub(r',\s*]', ']', json_content)  # Remove trailing commas in arrays
                json_content = re.sub(r'([{,])\s*([a-zA-Z0-9_]+)\s*:', r'\1"\2":', json_content)  # Add quotes to keys
                
                # For Mistral's format issues
                json_content = re.sub(r'True', r'"True"', json_content)  # Convert Python True to string
                json_content = re.sub(r'False', r'"False"', json_content)  # Convert Python False to string
                
                # Try to fix truncated JSON
                if "unexpected character" in str(e) or "Expecting" in str(e):
                    # Try to find the position of the error
                    match = re.search(r'char (\d+)', str(e))
                    if match:
                        error_pos = int(match.group(1))
                        # If the error is near the end, try truncating and completing the JSON
                        if error_pos > len(json_content) - 20:
                            # Find the last complete object or array
                            last_complete = max(json_content.rfind('}},'), json_content.rfind('}],'))
                            if last_complete > 0:
                                json_content = json_content[:last_complete+2] + '}}'
                
                try:
                    data = json.loads(json_content)
                    print("Successfully parsed JSON data after fixing format")
                    return data
                except json.JSONDecodeError:
                    pass  # Fall through to manual parsing
                    
        # If we didn't get valid JSON, try to parse questions manually
        print("Attempting manual question parsing...")
        questions = []
        
        # Look for question patterns with stronger pattern matching
        question_blocks = re.finditer(r'(?:Question\s*(\d+):|Q(\d+):|(\d+)\.)\s*([^\n\?]+\??)', response_text)
        
        for match in question_blocks:
            question_num = match.group(1) or match.group(2) or match.group(3)
            question_text = match.group(4).strip()
            
            if not question_text:
                continue
                
            # Find the start position of this question
            start_pos = match.start()
            
            # Find the next question or end of text
            next_match = re.search(r'(?:Question\s*\d+:|Q\d+:|\d+\.)\s*', response_text[start_pos + 1:])
            end_pos = start_pos + 1 + next_match.start() if next_match else len(response_text)
            
            # Extract the entire question block
            question_block = response_text[start_pos:end_pos]
            
            # Extract choices/options
            choices = []
            choices_match = re.search(r'(?:Options|Choices):\s*(.*?)(?:(?:Correct )?Answer:|Explanation:|$)', question_block, re.DOTALL)
            
            if choices_match:
                options_text = choices_match.group(1)
                if 'True/False' in options_text or 'True or False' in options_text:
                    choices = ['True', 'False']
                else:
                    # Try to extract lettered options (A, B, C, D)
                    option_matches = re.findall(r'(?:^|\n)\s*([A-D])(?:[.):]|\s*-\s*)\s*([^\n]+)', options_text)
                    if option_matches:
                        choices = [option.strip() for _, option in option_matches]
                    else:
                        # Try numbered options
                        option_matches = re.findall(r'(?:^|\n)\s*(\d+)(?:[.):]|\s*-\s*)\s*([^\n]+)', options_text)
                        if option_matches:
                            choices = [option.strip() for _, option in option_matches]
                        else:
                            # Try direct list of options
                            choices = [opt.strip() for opt in options_text.split('\n') if opt.strip()]
            
            # Extract correct answer
            answer = ""
            answer_match = re.search(r'(?:Correct )?Answer:\s*(.*?)(?:Explanation:|$)', question_block, re.DOTALL)
            if answer_match:
                answer = answer_match.group(1).strip()
                
                # If answer is a letter or number, convert to the actual option
                if re.match(r'^[A-D]$', answer) and len(choices) >= ord(answer) - ord('A') + 1:
                    answer = choices[ord(answer) - ord('A')]
                elif re.match(r'^\d+$', answer) and len(choices) >= int(answer):
                    answer = choices[int(answer) - 1]
            
            # Extract explanation
            explanation = "No explanation provided."
            explanation_match = re.search(r'Explanation:\s*(.*?)(?:$)', question_block, re.DOTALL)
            if explanation_match:
                explanation = explanation_match.group(1).strip()
            
            # Ensure we have at least the question and some choices before adding
            if question_text and choices:
                questions.append({
                    "question": question_text,
                    "choices": choices,
                    "correct_answer": answer if answer else choices[0] if choices else "",
                    "explanation": explanation
                })
        
        if questions:
            print(f"Manually parsed {len(questions)} questions")
            return {"questions": questions}
    
    except Exception as e:
        print(f"Error parsing response: {str(e)}")
        import traceback
        traceback.print_exc()
    
    # If all parsing attempts fail, return error
    return {
        "error": "Could not parse quiz questions from the model's response. This often happens when the content includes code examples or complex formatting. Try using simpler text content or content with fewer technical elements."
    } 