import ollama
import json
import re
import random

def generate_quiz(input_text, difficulty="medium", question_type="both", num_questions=5, topic="", lang: str = 'en'):
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
        
        # Difficulty-specific guidance
        difficulty = (difficulty or "medium").lower()
        difficulty_instructions_map = {
            "easy": (
                "Use simple factual recall questions. Avoid double negatives. "
                "MCQ distractors should be clearly wrong but plausible. Keep stems short."
            ),
            "medium": (
                "Use a mix of factual and conceptual questions. Require light reasoning. "
                "Distractors should be plausible and share surface similarity."
            ),
            "hard": (
                "Use application or multi-step reasoning questions. Incorporate subtle distinctions. "
                "Distractors should be highly plausible; avoid giveaways like 'all of the above'."
            ),
        }
        difficulty_instructions = difficulty_instructions_map.get(difficulty, difficulty_instructions_map["medium"]) 

        # Create the system prompt
        language_hint = f" Always use {lang} for all generated text (questions, choices, explanations)." if lang and lang.lower() != 'en' else ""
        system_prompt = f"""You are a quiz question generator.
DO NOT ASK TO CREATE QUESTIONS. DIRECTLY GENERATE ACTUAL QUIZ QUESTIONS.

Your task is to generate {num_questions} quiz questions and answers about the provided content.
Your response must be a valid JSON object with a 'questions' array containing multiple real questions.

Follow these difficulty instructions strictly: {difficulty_instructions}

IMPORTANT INSTRUCTIONS:
1. DO NOT return a meta-question asking to create questions. Create the actual questions yourself.
2. Generate exactly {num_questions} questions in JSON format.
3. If both types are requested, include a balanced mix of multiple-choice and true/false questions.
4. Each question must have these fields: 'question', 'choices', 'correct_answer', and 'explanation'.
5. The 'choices' field must be an array of strings.
6. For multiple-choice questions, include exactly 4 options in the choices array.
7. For true/false questions, use ["True", "False"] as the choices array.
8. Format your output as a single JSON object without any surrounding text.{language_hint}"""
        
        # Determine question type instructions
        question_type_instructions = ""
        if question_type == "mcq":
            question_type_instructions = "multiple-choice questions only with exactly 4 options each"
        elif question_type == "tf":
            question_type_instructions = "true/false questions only"
        else:  # "both"
            # Pre-compute target split for clarity to the model
            half = num_questions // 2
            other = num_questions - half
            question_type_instructions = (
                f"a balanced mix of multiple-choice (with exactly 4 options each) and true/false questions: "
                f"{other} multiple-choice and {half} true/false"
            )
        
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
                                # Normalize to choices to avoid dropping questions later
                                std_q["choices"] = answer["options"]
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
            # Fallback: generate deterministic quiz to avoid total failure
            print("Falling back to deterministic quiz generation")
            fallback = fallback_generate_quiz(input_text, num_questions=num_questions, question_type=question_type, topic=topic)
            return fallback
        
        # Ensure questions array exists and has the right structure
        if "questions" not in quiz_data or not quiz_data["questions"]:
            print("No questions found in parsed data")
            # Fallback: generate deterministic quiz to avoid total failure
            print("Falling back to deterministic quiz generation (no questions found)")
            return fallback_generate_quiz(input_text, num_questions=num_questions, question_type=question_type, topic=topic)
        
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
                # Normalize choices to strings for consistent handling
                "choices": [str(c).strip() for c in q["choices"]],
                "explanation": q.get("explanation", "No explanation provided.")
            }
            
            # Ensure correct_answer is a string, not a list
            if "correct_answer" in q:
                correct_answer = q["correct_answer"]
                # If correct_answer is a list, take the first item
                if isinstance(correct_answer, list):
                    correct_answer = correct_answer[0] if correct_answer else q["choices"][0]
                question["correct_answer"] = str(correct_answer)
            else:
                question["correct_answer"] = question["choices"][0]
            
            # Add type field based on choices
            # Ensure correct_answer present in choices
            if question.get("correct_answer") not in question["choices"]:
                # Try case-insensitive match
                ca = question.get("correct_answer", "")
                for c in question["choices"]:
                    if c.lower() == str(ca).lower():
                        question["correct_answer"] = c
                        break

            lower_choices = [c.lower() for c in question["choices"]]
            if len(lower_choices) == 2 and ("true" in lower_choices) and ("false" in lower_choices):
                question["type"] = "True/False"
                # Normalize TF choices order and correct answer
                question["choices"] = ["True", "False"]
                if str(question.get("correct_answer", "")).lower() in ("true", "false"):
                    question["correct_answer"] = str(question["correct_answer"]).title()
                else:
                    # Default to False if ambiguous
                    question["correct_answer"] = "False"
            else:
                question["type"] = "MCQ"
                
            valid_questions.append(question)

        # Helper to normalize/expand MCQs to 4 choices
        def ensure_mcq_has_four_choices(q_obj):
            if q_obj.get("type") != "MCQ":
                return q_obj
            choices = list(dict.fromkeys([c for c in q_obj.get("choices", []) if c]))  # dedupe, keep order
            correct = q_obj.get("correct_answer")
            if correct not in choices:
                choices.insert(0, correct)
            # Add generic, but neutral distractors if needed
            fallback_pool = [
                "Not mentioned in the text",
                "None of the above",
                "All of the above",
                "Insufficient information",
                "An unrelated concept",
            ]
            while len(choices) < 4 and fallback_pool:
                candidate = fallback_pool.pop(0)
                if candidate != correct and candidate not in choices:
                    choices.append(candidate)
            # If still not enough, duplicate with markers
            while len(choices) < 4:
                choices.append(f"Option {len(choices)+1}")
            q_obj["choices"] = choices[:4]
            if q_obj.get("correct_answer") not in q_obj["choices"]:
                q_obj["correct_answer"] = q_obj["choices"][0]
            return q_obj

        # Helper to convert TF to MCQ if needed
        def convert_tf_to_mcq(tf_q):
            stmt = tf_q.get("question", "").strip()
            correct = str(tf_q.get("correct_answer", "False")).title()
            # Build MCQ over truth evaluation
            choices = ["True", "False", "Not enough information", "It depends"]
            return {
                "question": stmt,
                "choices": choices,
                "correct_answer": correct if correct in ("True", "False") else "False",
                "explanation": tf_q.get("explanation", ""),
                "type": "MCQ",
            }

        # Filter questions based on the requested type
        if question_type == "mcq":
            mcq_only = [q for q in valid_questions if q["type"] == "MCQ"]
            # Top up MCQs by converting TF if needed
            if len(mcq_only) < num_questions:
                tf_pool = [q for q in valid_questions if q["type"] == "True/False"]
                for tfq in tf_pool:
                    if len(mcq_only) >= num_questions:
                        break
                    mcq_only.append(ensure_mcq_has_four_choices(convert_tf_to_mcq(tfq)))
            valid_questions = mcq_only
        elif question_type == "tf":
            tf_only = [q for q in valid_questions if q["type"] == "True/False"]
            if len(tf_only) < num_questions:
                # Convert MCQs to TF to fill up to the requested count
                mcq_pool = [q for q in valid_questions if q["type"] == "MCQ"]
                tf_generated = []
                i = 0
                while len(tf_only) + len(tf_generated) < num_questions and mcq_pool:
                    mcq = mcq_pool[i % len(mcq_pool)]
                    i += 1
                    # Alternate between true and false statements for variety
                    if (i % 2) == 1:
                        statement = f"{mcq['question'].rstrip('?').strip()} is {mcq['correct_answer']}."
                        tf_generated.append({
                            "question": statement,
                            "choices": ["True", "False"],
                            "correct_answer": "True",
                            "explanation": mcq.get("explanation", ""),
                            "type": "True/False"
                        })
                    else:
                        other_choices = [c for c in mcq.get("choices", []) if c != mcq.get("correct_answer")]
                        alternative = other_choices[0] if other_choices else "something else"
                        statement = f"{mcq['question'].rstrip('?').strip()} is {alternative}."
                        tf_generated.append({
                            "question": statement,
                            "choices": ["True", "False"],
                            "correct_answer": "False",
                            "explanation": mcq.get("explanation", ""),
                            "type": "True/False"
                        })
                valid_questions = tf_only + tf_generated
            else:
                valid_questions = tf_only
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
            
            # Calculate target split
            total_questions = min(len(valid_questions), num_questions)
            target_mcq = total_questions - (total_questions // 2)  # favor MCQ on odd
            target_tf = total_questions - target_mcq

            # If insufficient TF, convert from MCQ
            if len(tf_questions) < target_tf and len(mcq_questions) > 0:
                need = target_tf - len(tf_questions)
                for mcq in mcq_questions[:need]:
                    statement_true = f"{mcq['question'].rstrip('?').strip()} is {mcq['correct_answer']}."
                    tf_questions.append({
                        "question": statement_true,
                        "choices": ["True", "False"],
                        "correct_answer": "True",
                        "explanation": mcq.get("explanation", ""),
                        "type": "True/False",
                    })

            # If insufficient MCQ, convert from TF
            if len(mcq_questions) < target_mcq and len(tf_questions) > 0:
                need = target_mcq - len(mcq_questions)
                for tfq in tf_questions[:need]:
                    mcq_questions.append(ensure_mcq_has_four_choices(convert_tf_to_mcq(tfq)))

            # Normalize MCQs to have 4 choices
            mcq_questions = [ensure_mcq_has_four_choices(q) for q in mcq_questions]

            # If still short overall, try topping up by converting whichever pool has more
            combined = mcq_questions[:target_mcq] + tf_questions[:target_tf]
            while len(combined) < total_questions:
                # Prefer converting MCQ to TF if we have surplus MCQs, else TF to MCQ
                if len(mcq_questions) > target_mcq:
                    mcq = mcq_questions[target_mcq]
                    combined.append({
                        "question": f"{mcq['question'].rstrip('?').strip()} is {mcq['correct_answer']}.",
                        "choices": ["True", "False"],
                        "correct_answer": "True",
                        "explanation": mcq.get("explanation", ""),
                        "type": "True/False",
                    })
                    target_tf += 1
                elif len(tf_questions) > target_tf:
                    tfq = tf_questions[target_tf]
                    combined.append(ensure_mcq_has_four_choices(convert_tf_to_mcq(tfq)))
                    target_mcq += 1
                else:
                    break
            # Construct the final balanced list to exact target counts
            valid_questions = combined[:total_questions]
            print(f"Created balanced question mix: {len(mcq_questions[:target_mcq])} MCQ, {len(tf_questions[:target_tf])} T/F")
            
        # Check if we have any valid questions after filtering
        if not valid_questions:
            print("Valid questions list empty after normalization, using fallback generator")
            return fallback_generate_quiz(input_text, num_questions=num_questions, question_type=question_type, topic=topic)
            
        # Normalize final questions by type
        for q in valid_questions:
            if q.get("type") == "MCQ":
                ensure_mcq_has_four_choices(q)
            elif q.get("type") == "True/False":
                q["choices"] = ["True", "False"]
                if str(q.get("correct_answer", "")).lower() in ("true", "false"):
                    q["correct_answer"] = str(q["correct_answer"]).title()
                else:
                    q["correct_answer"] = "False"

        # Trim to requested number of questions
        valid_questions = valid_questions[:num_questions]
        print(f"Successfully generated {len(valid_questions)} valid questions")
        return {"questions": valid_questions}
        
    except Exception as e:
        print(f"Error generating quiz: {str(e)}")
        import traceback
        traceback.print_exc()
        # As a last resort, try fallback generation
        try:
            return fallback_generate_quiz(input_text, num_questions=num_questions, question_type=question_type, topic=topic)
        except Exception:
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
        
        # Normalize smart quotes and stray characters
        response_text = response_text.replace('“', '"').replace('”', '"').replace('’', "'").replace('‘', "'")
        
        # Remove Markdown code fences and language hints
        response_text_clean = re.sub(r"```[a-zA-Z]*", "```", response_text)
        
        # Find JSON content in the response (handles when model includes other text)
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```|```([\s\S]*?)```|\{[\s\S]*\}|\[[\s\S]*\]', response_text_clean)
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
            # Strip JavaScript-style comments
            json_content = re.sub(r"//.*", "", json_content)
            json_content = re.sub(r"/\*[\s\S]*?\*/", "", json_content)
            
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
                json_content = json_content.replace('\n', '\n')
                
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
                
                # As a stronger attempt, try extracting a balanced JSON object manually
                balanced = _extract_balanced_json_object(response_text_clean)
                if balanced:
                    try:
                        data = json.loads(balanced)
                        print("Successfully parsed balanced JSON object")
                        return data
                    except Exception:
                        pass
                
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


def _extract_balanced_json_object(text: str) -> str:
    """Extract the first balanced top-level JSON object from text, if present."""
    start = text.find('{')
    if start == -1:
        return ''
    stack = []
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
            continue
        else:
            if ch == '"':
                in_string = True
            elif ch == '{':
                stack.append('{')
            elif ch == '}':
                if stack:
                    stack.pop()
                    if not stack:
                        return text[start:i+1]
    return ''


def fallback_generate_quiz(input_text: str, num_questions: int = 5, question_type: str = "both", topic: str = "") -> dict:
    """Deterministic quiz generator used as a safety net when LLM parsing fails."""
    # Basic sentence extraction
    sentences = re.split(r'(?<=[.!?])\s+', input_text)
    sentences = [s.strip() for s in sentences if 40 <= len(s.strip()) <= 220]
    # If not enough mid-length sentences, relax
    if len(sentences) < num_questions:
        sentences = [s.strip() for s in re.split(r'\n+|(?<=[.!?])\s+', input_text) if len(s.strip()) >= 20]

    def make_tf(s: str) -> dict:
        question = f"True or False: {s.rstrip()}"
        return {
            "question": question,
            "choices": ["True", "False"],
            "correct_answer": "True",
            "explanation": "This statement comes directly from the provided content.",
            "type": "True/False",
        }

    def make_mcq(s: str) -> dict:
        # Try to pick a salient token as answer
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", s)
        numbers = re.findall(r"\b\d+\b", s)
        answer = ''
        if numbers:
            answer = numbers[0]
        elif tokens:
            # Prefer capitalized token or mid-length noun-like token
            preferred = [t for t in tokens if t[0].isupper() and len(t) <= 16]
            answer = (preferred[0] if preferred else tokens[0])
        else:
            answer = s.split(' ')[0]

        choices_pool = [
            answer,
            "Not mentioned in the text",
            "None of the above",
            "Insufficient information",
            "It depends on the context",
        ]
        # Deduplicate and take first 4
        seen = set()
        choices = []
        for c in choices_pool:
            if c not in seen:
                seen.add(c)
                choices.append(c)
            if len(choices) == 4:
                break
        return {
            "question": "Which of the following is referenced by the content?",
            "choices": choices,
            "correct_answer": answer,
            "explanation": "The correct option appears in or is supported by the provided content.",
            "type": "MCQ",
        }

    generated = []
    # Decide composition
    desired = num_questions
    if question_type == "mcq":
        for s in sentences[:desired]:
            generated.append(make_mcq(s))
    elif question_type == "tf":
        for s in sentences[:desired]:
            generated.append(make_tf(s))
    else:  # both
        half = desired // 2
        for s in sentences[:half]:
            generated.append(make_mcq(s))
        for s in sentences[half:desired]:
            generated.append(make_tf(s))

    # If still short, pad with generic questions
    while len(generated) < desired:
        idx = len(generated) + 1
        generated.append({
            "question": f"According to the content, statement {idx} is ______.",
            "choices": ["True", "False", "Not mentioned in the text", "Cannot be determined"],
            "correct_answer": "Not mentioned in the text",
            "explanation": "This is a generic filler to reach the requested number of questions.",
            "type": "MCQ",
        })

    # Trim and normalize
    generated = generated[:desired]
    return {"questions": generated}