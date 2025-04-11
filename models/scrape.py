import requests
from bs4 import BeautifulSoup
import ollama
import time
import re
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

def web_scrape(query, scrape_type='search', max_results=5):
    """
    Scrape web content based on query
    scrape_type: 'search' for Bing search results, 'content' for webpage content
    """
    if scrape_type == 'search':
        return search_bing(query, max_results)
    elif scrape_type == 'content':
        return scrape_website(query)
    else:
        return "Invalid scrape type"

def search_bing(query, max_results=5):
    """Perform a Bing search and return a list of results."""
    search_url = f"https://www.bing.com/search?q={query}"

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")

    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        driver.get(search_url)
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CLASS_NAME, "b_algo")))
        html = driver.page_source
    except Exception as e:
        return {"error": str(e)}
    finally:
        if 'driver' in locals():
            driver.quit()

    soup = BeautifulSoup(html, "html.parser")
    search_results = soup.find_all("li", class_="b_algo")

    results = []
    for result in search_results[:max_results]:
        a_tag = result.find("a")
        title_tag = result.find("h2")

        if a_tag and title_tag:
            title = title_tag.get_text(strip=True)
            url = a_tag.get("href")
            if title and url:
                results.append({"title": title, "url": url})

    return results

def scrape_website(url):
    """Scrape content from a given website."""
    print(f"Scraping website: {url}")
    
    # Clean and normalize URL
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    print(f"Normalized URL: {url}")
    
    # For simple websites, use requests instead of Selenium
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.google.com/',
            'DNT': '1'  # Do Not Track request header
        }
        print(f"Trying with requests first...")
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            print(f"Request failed with status code: {response.status_code}")
            return f"Error: Status code {response.status_code}"
        
        html = response.text
        print(f"Successfully fetched page with requests, HTML size: {len(html)} characters")
        
        # Check content type to ensure we're processing HTML
        content_type = response.headers.get('Content-Type', '')
        if 'text/html' not in content_type.lower():
            print(f"Warning: Content-Type is not HTML: {content_type}")
        
        content = extract_body_content(html)
        
        # If content extraction was successful with requests, return it
        if content and content != "No relevant content found." and len(content) > 100:
            print(f"Content extraction successful with requests")
            return content
            
        # If not enough content was found, try using Selenium
        print("Simple extraction insufficient, trying Selenium...")
    except requests.RequestException as e:
        print(f"Request exception: {e}")
        html = None
    
    # Fall back to Selenium for more complex sites or JavaScript-heavy pages
    try:
        print(f"Setting up Selenium...")
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")  # Larger window size
        options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        options.add_argument("--disable-blink-features=AutomationControlled")  # Avoid detection
        
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        
        print(f"Navigating to URL with Selenium: {url}")
        driver.get(url)
        
        # Wait for the page to load
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        print(f"Page loaded in Selenium")
        
        # Handle cookie consent popups and other common overlays
        try:
            for consent_text in ["accept", "agree", "consent", "accept all", "i agree"]:
                buttons = driver.find_elements(By.XPATH, f"//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{consent_text}')]")
                for button in buttons:
                    if button.is_displayed():
                        print(f"Clicking consent button: {button.text}")
                        button.click()
                        time.sleep(1)
                        break
        except Exception as e:
            print(f"Error handling cookie consent: {e}")

        # Scroll to load lazy content
        print(f"Scrolling to load lazy content...")
        last_height = driver.execute_script("return document.body.scrollHeight")
        for i in range(5):  # Increased scroll attempts
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script("return document.body.scrollHeight")
            print(f"Scroll {i+1}: Height changed from {last_height} to {new_height}")
            if new_height == last_height:
                break
            last_height = new_height

        # Wait for dynamic content to load
        print(f"Waiting for any remaining dynamic content...")
        time.sleep(3)
        
        # Try to expand relevant sections (common in educational sites)
        try:
            expand_buttons = driver.find_elements(By.XPATH, "//button[contains(text(), 'Read more')]|//button[contains(text(), 'Show more')]|//a[contains(text(), 'Expand')]")
            for button in expand_buttons[:5]:  # Limit to first 5 to avoid too many clicks
                if button.is_displayed():
                    print(f"Clicking expand button: {button.text}")
                    button.click()
                    time.sleep(1)
        except Exception as e:
            print(f"Error expanding content sections: {e}")

        html = driver.page_source
        print(f"Retrieved page source with Selenium, HTML size: {len(html)} characters")
        
        # Get all links for potential pagination or content expansion
        links = []
        try:
            elements = driver.find_elements(By.TAG_NAME, "a")
            for element in elements:
                href = element.get_attribute('href')
                if href and ('page' in href or 'next' in href.lower() or 'continue' in href.lower()):
                    links.append(href)
            if links:
                print(f"Found {len(links)} pagination links")
        except Exception as e:
            print(f"Error getting links: {e}")
            
    except Exception as e:
        print(f"Selenium error: {str(e)}")
        return f"Error during scraping: {str(e)}"
    finally:
        if 'driver' in locals():
            driver.quit()
            print(f"Selenium driver closed")

    # Try to extract content from the HTML
    try:
        print(f"Extracting content from HTML...")
        content = extract_body_content(html)
        print(f"Content extraction complete. Content length: {len(content)}")
        return content
    except Exception as e:
        print(f"Error in content extraction: {str(e)}")
        return f"Error extracting content: {str(e)}"

def extract_body_content(html_content):
    """Extract the main content from the scraped HTML."""
    if not html_content:
        return "No content to extract."
        
    soup = BeautifulSoup(html_content, "html.parser")
    print(f"Extracting content from HTML of size {len(html_content)}")

    # Remove unwanted elements
    for tag in soup.find_all(["script", "style", "form", "footer", "aside", "nav", "header", "button", "iframe", "noscript"]):
        tag.decompose()

    # Try to find main content with common content containers
    content_elements = []
    
    # Look for potential content containers with more specific selectors
    potential_containers = [
        soup.find("main"),
        soup.find("article"),
        soup.find("div", {"id": re.compile("content|article|main|post|body", re.I)}),
        soup.find("div", {"class": re.compile("content|article|main|post|body", re.I)}),
        soup.find("section", {"id": re.compile("content|article|main|post|body", re.I)}),
        soup.find("section", {"class": re.compile("content|article|main|post|body", re.I)})
    ]
    
    # Filter out None values
    potential_containers = [container for container in potential_containers if container]
    
    if potential_containers:
        # Find the container with the most text content
        most_content_container = max(potential_containers, 
                                    key=lambda container: len(''.join(p.get_text() for p in container.find_all('p'))))
        content_elements.append(most_content_container)
    else:
        # If no specific containers found, use the body
        content_elements.append(soup.body)

    # Extract content from each element type
    all_content = []
    
    # Process headings in order (h1, h2, h3, h4)
    for container in content_elements:
        for heading_tag in ['h1', 'h2', 'h3', 'h4']:
            headings = container.find_all(heading_tag)
            for h in headings:
                text = h.get_text(strip=True)
                if text and len(text) > 3:  # Avoid empty or too short headings
                    all_content.append(f"\n## {text}\n")
    
    # Process paragraphs and list items
    for container in content_elements:
        # Extract paragraphs with meaningful content
        paragraphs = container.find_all('p')
        for p in paragraphs:
            text = p.get_text(strip=True)
            if text and len(text) > 10:  # Avoid very short paragraphs
                all_content.append(text)
        
        # Extract list items
        lists = container.find_all(['ul', 'ol'])
        for list_element in lists:
            items = list_element.find_all('li')
            for item in items:
                text = item.get_text(strip=True)
                if text and len(text) > 5:
                    all_content.append(f"- {text}")
    
    # Extract div content when it might contain important text not in paragraphs
    for container in content_elements:
        divs = container.find_all('div', recursive=False)
        for div in divs:
            # Check if div contains paragraphs or other structured content
            if not div.find_all(['p', 'ul', 'ol', 'h1', 'h2', 'h3', 'h4']):
                text = div.get_text(strip=True)
                if text and len(text) > 50:  # Only include substantial div content
                    all_content.append(text)
    
    # Join all content with appropriate spacing
    cleaned_text = "\n\n".join(all_content)
    
    # Remove consecutive newlines and extra spaces
    cleaned_text = re.sub(r'\n{3,}', '\n\n', cleaned_text)
    cleaned_text = re.sub(r' {2,}', ' ', cleaned_text)
    
    print(f"Extracted content length: {len(cleaned_text)}")
    return cleaned_text if cleaned_text.strip() else "No relevant content found."

def parse_content(content, question):
    """Use Ollama to generate an answer based on the scraped content."""
    # Split content into manageable chunks
    max_length = 6000
    chunks = [content[i:i + max_length] for i in range(0, len(content), max_length)]
    
    # If multiple chunks, use first chunk but inform about total content
    if len(chunks) > 1:
        chunk_intro = f"This is part 1 of {len(chunks)} from the extracted content. "
    else:
        chunk_intro = ""
    
    prompt = f"""{chunk_intro}Based on the following content:
    
    {chunks[0]}
    
    Answer this question: {question}
    
    Give a clear, concise answer using only the information in the content.
    If the content doesn't contain the answer, state that clearly.
    """
    
    try:
        response = ollama.chat(model="mistral", messages=[{"role": "user", "content": prompt}])
        return response['message']['content']
    except Exception as e:
        return f"Error generating response: {str(e)}" 