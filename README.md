# 🎓 EduSmartBot - AI-Powered Education Tool

<div align="center">

```ascii
  ______    _      _____                      _   
 |  ____|  | |    / ____|                    | |  
 | |__   __| |_  | (___  _ __ ___   __ _ _ __| |_ 
 |  __| / _` | | |\___ \| '_ ` _ \ / _` | '__| __|
 | |___| (_| | | |____) | | | | | | (_| | |  | |_ 
 |______\__,_|_| |_____/|_| |_| |_|\__,_|_|   \__|
                                                 
```

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/flask-2.0.0-green.svg)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Ollama](https://img.shields.io/badge/ollama-0.1.0-orange.svg)](https://ollama.ai/)
[![Tesseract OCR](https://img.shields.io/badge/tesseract-ocr-yellow.svg)](https://github.com/tesseract-ocr/tesseract)
[![Contributors](https://img.shields.io/badge/contributors-2-brightgreen.svg)](https://github.com/Pragadees15/EduSmartBot/graphs/contributors)

</div>

## 🚀 About EduSmartBot

EduSmartBot is your AI-powered educational companion that transforms learning into an engaging and interactive experience. Built with cutting-edge AI technologies, it's designed to make education more accessible, personalized, and fun!

<div align="center">
  <img src="https://img.shields.io/badge/Web%20Scraper-FF6B6B?style=for-the-badge" alt="Web Scraper">
  <img src="https://img.shields.io/badge/OCR%20Tool-4ECDC4?style=for-the-badge" alt="OCR Tool">
  <img src="https://img.shields.io/badge/AI%20Chatbot-45B7D1?style=for-the-badge" alt="AI Chatbot">
  <img src="https://img.shields.io/badge/Quiz%20Generator-96CEB4?style=for-the-badge" alt="Quiz Generator">
</div>

## 🌟 Key Features

<div align="center">
  <table>
    <tr>
      <td width="25%" align="center">
        <span style="font-size:48px">🌐</span>
        <br>
        <b>Web Scraper</b>
        <br>
        <sub>AI-powered content extraction</sub>
      </td>
      <td width="25%" align="center">
        <span style="font-size:48px">📑</span>
        <br>
        <b>OCR Tool</b>
        <br>
        <sub>Smart text extraction</sub>
      </td>
      <td width="25%" align="center">
        <span style="font-size:48px">🤖</span>
        <br>
        <b>AI Chatbot</b>
        <br>
        <sub>Interactive learning</sub>
      </td>
      <td width="25%" align="center">
        <span style="font-size:48px">📝</span>
        <br>
        <b>Quiz Generator</b>
        <br>
        <sub>Custom knowledge tests</sub>
      </td>
    </tr>
  </table>
</div>

## 🛠️ Tech Stack

<div align="center">
  <img src="https://img.shields.io/badge/Python-FFD43B?style=for-the-badge&logo=python&logoColor=blue" alt="Python">
  <img src="https://img.shields.io/badge/Flask-000000?style=for-the-badge&logo=flask&logoColor=white" alt="Flask">
  <img src="https://img.shields.io/badge/Ollama-FF6B6B?style=for-the-badge&logo=ollama&logoColor=white" alt="Ollama">
  <img src="https://img.shields.io/badge/Tesseract-000000?style=for-the-badge&logo=tesseract&logoColor=white" alt="Tesseract">
  <img src="https://img.shields.io/badge/Bootstrap-563D7C?style=for-the-badge&logo=bootstrap&logoColor=white" alt="Bootstrap">
</div>

## 🚀 Quick Start

```bash
# Clone the repository
git clone https://github.com/Pragadees15/EduSmartBot.git
cd EduSmartBot

# Create and activate virtual environment
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## 📋 Prerequisites

- Python 3.8+
- Flask
- Ollama (for local AI models)
- Tesseract OCR
- Chrome/Chromium browser (for web scraping)

## 🛠️ Installation Guide

1. **Install Ollama**:
   ```bash
   # Follow instructions at https://ollama.ai/
   ollama pull mistral
   ollama pull llava  # For vision features
   ```

2. **Install Tesseract OCR**:
   - Windows: Download from [Tesseract 5.5.0](https://github.com/tesseract-ocr/tesseract/releases/tag/5.5.0)
   - macOS: `brew install tesseract`
   - Linux: `sudo apt install tesseract-ocr`

3. **Set up ChromeDriver**:
   - Download from [ChromeDriver](https://chromedriver.chromium.org/downloads)
   - Place in application directory or system PATH

## 🏃‍♂️ Running the Application

1. Start Ollama server:
   ```bash
   ollama serve
   ```

2. Start Flask application:
   ```bash
   python app.py
   ```

3. Open your browser:
   ```
   http://127.0.0.1:5000/
   ```

## 📁 Project Structure

```
EduSmartApp/
│
├── app.py                  # Main Flask application
├── uploads/                # Directory for uploaded files
│
├── models/                 # Backend model files
│   ├── scrape.py           # Web scraping module
│   ├── ocr.py              # OCR processing module
│   ├── chatbot.py          # Chatbot module
│   └── quiz.py             # Quiz generation module
│
├── static/                 # Static assets
│   ├── css/                # CSS stylesheets
│   ├── js/                 # JavaScript files
│   └── images/             # Image assets
│
└── templates/              # HTML templates
    ├── base.html           # Base template
    ├── index.html          # Homepage
    ├── web_scraper.html    # Web scraper page
    ├── ocr.html            # OCR tool page
    ├── chatbot.html        # Chatbot page
    └── quiz.html           # Quiz generator page
```

## 👥 Contributors

<div align="center">
  <table>
    <tr>
      <td align="center">
        <a href="https://github.com/Pragadees15">
          <img src="https://github.com/Pragadees15.png" width="100px;" alt="Pragadeeswaran"/>
          <br />
          <sub><b>Pragadeeswaran K</b></sub>
        </a>
        <br />
        <sub>Core Developer & Maintainer</sub>
        <br />
        <a href="https://github.com/Pragadees15" title="GitHub Profile">🔗 GitHub</a>
      </td>
      <td align="center">
        <a href="https://github.com/Pranav-Aditya016">
          <img src="https://github.com/Pranav-Aditya016.png" width="100px;" alt="Pranav Aditya"/>
          <br />
          <sub><b>Pranav Aditya</b></sub>
        </a>
        <br />
        <sub>Core Developer</sub>
        <br />
        <a href="https://github.com/Pranav-Aditya016" title="GitHub Profile">🔗 GitHub</a>
      </td>
    </tr>
  </table>
</div>

## 📚 Dependencies

See `requirements.txt` for a full list of dependencies.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgements

- Uses Ollama for local AI model hosting
- Bootstrap 5 for UI components
- Font Awesome for icons
- Flask for web framework
- Tesseract OCR for text extraction
- ChromeDriver for web automation

---

<div align="center">
  <sub>Built with ❤️ by <a href="https://github.com/Pragadees15">Pragadeeswaran K</a> and the EduSmartBot team</sub>
  <br>
  <sub>✨ Making education smarter, one AI at a time ✨</sub>
</div> 