import pytesseract
import pdfplumber
from PIL import Image
import cv2
import numpy as np
import ollama
import base64
import os
import re
from docx import Document

# Function to extract text from PDFs using pdfplumber
def extract_text_from_pdf(file_path):
    with pdfplumber.open(file_path) as pdf:
        text = "\n".join([page.extract_text() for page in pdf.pages if page.extract_text()])
    return text.strip()

# Function to extract text from images using PyTesseract OCR
def extract_text_from_image(file_path):
    image = Image.open(file_path)
    text = pytesseract.image_to_string(image).strip()
    return text

# Function to extract text from DOCX files
def extract_text_from_docx(file_path):
    try:
        doc = Document(file_path)
        text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
        return text.strip()
    except Exception as e:
        print(f"Error extracting text from DOCX: {str(e)}")
        return f"Error extracting text from DOCX: {str(e)}"

# Main function to extract text from a file
def extract_text_from_file(file_path):
    try:
        # Check if file exists
        if not os.path.exists(file_path):
            print(f"Error: File not found at path {file_path}")
            return "Error: File not found"
            
        file_extension = os.path.splitext(file_path)[1].lower()
        
        if file_extension == '.pdf':
            try:
                return extract_text_from_pdf(file_path)
            except Exception as e:
                print(f"Error extracting text from PDF: {str(e)}")
                return f"Error extracting text from PDF: {str(e)}"
        elif file_extension in ['.png', '.jpg', '.jpeg']:
            try:
                # Always use the vision model for image processing
                return analyze_image_with_vision_model(file_path)
            except Exception as e:
                print(f"Error extracting text from image: {str(e)}")
                return f"Error extracting text from image: {str(e)}"
        elif file_extension == '.txt':
            try:
                with open(file_path, 'r', encoding='utf-8') as file:
                    return file.read()
            except Exception as e:
                print(f"Error reading text file: {str(e)}")
                return f"Error reading text file: {str(e)}"
        elif file_extension in ['.docx', '.doc']:
            try:
                return extract_text_from_docx(file_path)
            except Exception as e:
                print(f"Error extracting text from DOCX: {str(e)}")
                return f"Error extracting text from DOCX: {str(e)}"
        else:
            return "Unsupported file format"
    except Exception as e:
        print(f"Unexpected error in extract_text_from_file: {str(e)}")
        return f"Error processing file: {str(e)}"

def detect_if_diagram(image_path):
    """Detect if the image is likely a diagram based on edge detection"""
    image = cv2.imread(image_path)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    
    # Count edges and determine if it's likely a diagram
    edge_count = np.sum(edges > 0)
    total_pixels = edges.shape[0] * edges.shape[1]
    edge_ratio = edge_count / total_pixels
    
    # Diagrams typically have more edges than regular text/photos
    return edge_ratio > 0.05

def analyze_image_with_vision_model(image_path):
    """Analyze image with vision-capable LLM"""
    try:
        # Get image data as base64
        with open(image_path, "rb") as image_file:
            image_bytes = image_file.read()
            encoded_image = base64.b64encode(image_bytes).decode("utf-8")
        
        print("Using granite3.2-vision model for image analysis...")
        
        try:
            # Use the granite3.2-vision model
            response = ollama.chat(
                model="granite3.2-vision:latest",
                messages=[
                    {
                        "role": "system", 
                        "content": "You are an expert OCR assistant that can extract and analyze text from images. Extract all visible text, explain diagrams, and organize the content in a structured way."
                    },
                    {
                        "role": "user", 
                        "content": "Please extract and analyze all text and visual elements from this image. If it contains diagrams, charts, or other visual elements, please describe them in detail as well.",
                        "images": [encoded_image]
                    }
                ]
            )
            print("Successfully processed image with vision model")
            return response['message']['content']
        except Exception as e:
            print(f"Error with vision model: {str(e)}. Falling back to OCR...")
            # Fallback to standard OCR if vision model fails
            return extract_text_from_image(image_path)
            
    except Exception as e:
        print(f"Error analyzing image: {str(e)}")
        return f"Error analyzing image: {str(e)}"

def process_ocr_question(content, question):
    """Process a question based on OCR content"""
    prompt = f"""Based on the following extracted content:
    
    {content}
    
    Answer this question: {question}
    
    Give a clear, educational answer using only information from the content.
    If the information is not available in the content, state that clearly.
    """
    
    try:
        response = ollama.chat(model="mistral:latest", messages=[{"role": "user", "content": prompt}])
        return response['message']['content']
    except Exception as e:
        return f"Error processing question: {str(e)}" 