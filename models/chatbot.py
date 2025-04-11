import requests
import json
import os
import re

def clean_response(text):
    """Removes AI thinking patterns and formats response"""
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    return text.strip()

def get_chatbot_response(message, chat_history=None):
    """
    Get response from Ollama chatbot model
    """
    try:
        # Replace default response with personalized introduction if user asks about name
        if any(name_query in message.lower() for name_query in ["what's your name", "what is your name", "who are you"]):
            return "My name is EduBuddy! I'm your dedicated educational assistant designed to help you learn and understand various academic concepts. How can I assist with your educational journey today?"

        # Format chat history for the model
        formatted_history = []
        if chat_history:
            for msg in chat_history:
                if msg['role'] == 'user':
                    formatted_history.append({"role": "user", "content": msg['content']})
                elif msg['role'] == 'assistant':
                    formatted_history.append({"role": "assistant", "content": msg['content']})
        
        # Add system message to give the chatbot an educational identity
        system_message = {
            "role": "system", 
            "content": "You are EduBuddy, a helpful and knowledgeable educational assistant. Your purpose is to explain academic concepts clearly, answer educational questions accurately, and help students learn effectively. Always introduce yourself as EduBuddy when asked about your identity."
        }
        
        # Build messages array with system message first
        messages = [system_message]
        
        # Add chat history if available
        if formatted_history:
            messages.extend(formatted_history)
        else:
            # If no history, add the current message
            messages.append({"role": "user", "content": message})
        
        # Make request to Ollama API
        response = requests.post(
            'http://localhost:11434/api/chat',
            headers={"Content-Type": "application/json"},
            data=json.dumps({
                "model": "mistral",
                "messages": messages,
                "stream": False
            })
        )
        
        if response.status_code == 200:
            response_data = response.json()
            return response_data['message']['content']
        else:
            return f"Error: Unable to connect to the model. Status code: {response.status_code}"
    
    except Exception as e:
        return f"I apologize, but I encountered an error: {str(e)}. Please try again later." 