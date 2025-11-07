import os
import json
import time
import re
import tempfile
from urllib.parse import quote_plus, urlparse, parse_qs, urljoin
import base64

import requests
from bs4 import BeautifulSoup
import ollama
from readability import Document
from typing import List, Dict, Optional

def web_scrape(query, scrape_type='search', max_results=5, include_images: bool = False):
    """
    Scrape web content based on query.
    scrape_type: 'search' for Google search results, 'content' for webpage content
    """
    if scrape_type == 'search':
        return search_google(query, max_results)
    elif scrape_type == 'content':
        return scrape_website(query, include_images=include_images)
    else:
        return "Invalid scrape type"

def search_google(query, max_results=5):
    """Search the web (DuckDuckGo HTML) and return simple results.

    This avoids headless browsers and works reliably without Selenium.
    """
    max_results = max(1, int(max_results or 5))

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://duckduckgo.com/'
        }
        params = {
            'q': query,
            'kl': 'us-en'
        }
        # Use the lite HTML endpoint
        resp = requests.get('https://duckduckgo.com/html/', params=params, headers=headers, timeout=20)
        soup = BeautifulSoup(resp.text, 'html.parser')
        results = []
        for res in soup.select('a.result__a'):
            title = res.get_text(strip=True)
            href = res.get('href')
            if not href:
                continue
            # DDG uses "/l/?kh=-1&uddg=<encoded_url>" sometimes; try to decode
            try:
                parsed = urlparse(href)
                if parsed.netloc.endswith('duckduckgo.com'):
                    q = parse_qs(parsed.query).get('uddg', [])
                    href = q[0] if q else href
            except Exception:
                pass
            if href.startswith('http'):
                results.append({"title": title, "url": href})
            if len(results) >= max_results:
                break
        return results
    except Exception as e:
        return {"error": f"search failed: {str(e)}"}


def search_with_similarity(query: str, max_results: int = 5, include_images: bool = False) -> list[dict]:
    """Search and return results ranked by similarity with snippet and score."""
    # Fetch more candidates to allow better ranking
    fetch_n = max(max_results, 10)
    base = search_google(query, max_results=fetch_n)
    if isinstance(base, dict) and base.get('error'):
        return base
    docs = []
    for r in (base or [])[:fetch_n]:
        url = r.get('url')
        if not url:
            continue
        content = _fetch_and_extract(url, include_images=include_images)
        if not content:
            continue
        snippet = _make_snippet(content, query)
        docs.append({'title': r.get('title'), 'url': url, 'content': content, 'snippet': snippet})
    if not docs:
        return []
    ranked = _similarity_rank(query, docs)
    # Map to lightweight payload
    out = []
    for d in ranked[:max_results]:
        out.append({'title': d.get('title'), 'url': d.get('url'), 'similarity': d.get('score'), 'snippet': d.get('snippet')})
    return out

SCRAPE_ENABLE_IMAGE_VISION = os.environ.get('SCRAPE_ENABLE_IMAGE_VISION', 'false').lower() == 'true'
SCRAPE_IMAGE_MAX = int(os.environ.get('SCRAPE_IMAGE_MAX', '5'))
SCRAPE_IMAGE_MAX_BYTES = int(os.environ.get('SCRAPE_IMAGE_MAX_BYTES', str(2 * 1024 * 1024)))  # 2MB default
SCRAPE_REQUEST_TIMEOUT_SECONDS = float(os.environ.get('SCRAPE_REQUEST_TIMEOUT_SECONDS', '20'))
SCRAPE_TABLES_AS_MARKDOWN = os.environ.get('SCRAPE_TABLES_AS_MARKDOWN', 'true').lower() == 'true'


def scrape_website(url, include_images: bool = False):
    """Scrape content from a given website."""
    print(f"Scraping website: {url}")
    
    # Clean and normalize URL
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    print(f"Normalized URL: {url}")
    
    # Fetch via requests; avoid Selenium for simplicity and portability
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.google.com/',
            'DNT': '1'  # Do Not Track request header
        }
        print(f"Trying with requests first...")
        response = requests.get(url, headers=headers, timeout=SCRAPE_REQUEST_TIMEOUT_SECONDS, allow_redirects=True)
        if response.status_code != 200:
            print(f"Request failed with status code: {response.status_code}")
            return f"Error: Status code {response.status_code}"
        
        # Handle PDFs and other non-HTML content types
        content_type = (response.headers.get('Content-Type') or '').lower()
        if 'application/pdf' in content_type or url.lower().endswith('.pdf'):
            print("Detected PDF content. Downloading and extracting text...")
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmpf:
                    tmpf.write(response.content)
                    tmp_pdf_path = tmpf.name
                # Lazy import to avoid circular deps on module import
                from models.ocr import extract_text_from_file as extract_text_from_file_ocr
                pdf_text = extract_text_from_file_ocr(tmp_pdf_path)
                try:
                    os.remove(tmp_pdf_path)
                except Exception:
                    pass
                return pdf_text or "No text extracted from PDF."
            except Exception as e:
                print(f"Error extracting PDF: {e}")
                return f"Error extracting PDF content: {str(e)}"

        html = response.text
        print(f"Successfully fetched page with requests, HTML size: {len(html)} characters")
        
        # Check content type to ensure we're processing HTML
        if 'text/html' not in content_type:
            print(f"Warning: Content-Type is not HTML: {content_type}")
        
        content = extract_body_content(html, base_url=url, enable_image_vision=include_images)
        
        # If content extraction was successful with requests, return it
        if content and content != "No relevant content found." and len(content) > 100:
            print(f"Content extraction successful with requests")
            return content
            
        # If not enough content was found, try a stronger readability extraction
        print("Simple extraction insufficient, trying readability extraction...")
        readable = extract_with_readability(html)
        if readable and len(readable) > 100:
            return readable
    except requests.RequestException as e:
        print(f"Request exception: {e}")
        html = None
    
    # If we still have HTML (from earlier), try readability; else return error
    if html:
        try:
            readable = extract_with_readability(html)
            if readable and len(readable) > 50:
                return readable
        except Exception as e:
            print(f"Readability fallback failed: {e}")
    return "No relevant content found."

    # Try to extract content from the HTML
    # Unused path after simplification
    pass

def extract_with_readability(html: str) -> str:
    """Use readability-lxml to extract main content as markdown-like text."""
    try:
        doc = Document(html)
        summary_html = doc.summary(html_partial=True)
        soup = BeautifulSoup(summary_html, 'html.parser')
        # Convert simple structure to text with headings and lists
        parts = []
        title = (doc.short_title() or '').strip()
        if title:
            parts.append(f"## {title}")
        for el in soup.find_all(['h1','h2','h3','p','li','table']):
            if el.name in ('h1','h2','h3'):
                text = el.get_text(strip=True)
                if text:
                    parts.append(f"\n## {text}\n")
            elif el.name == 'li':
                text = el.get_text(strip=True)
                if text:
                    parts.append(f"- {text}")
            elif el.name == 'table':
                parts.append(_table_to_markdown(el))
            else:
                text = el.get_text(strip=True)
                if text:
                    parts.append(text)
        out = "\n\n".join([p for p in parts if p])
        out = re.sub(r'\n{3,}', '\n\n', out)
        return out.strip()
    except Exception:
        return ""

def extract_body_content(html_content, base_url: str = '', enable_image_vision: bool | None = None):
    """Extract the main content from the scraped HTML.

    If SCRAPE_ENABLE_IMAGE_VISION=true, attempts image OCR/vision on key images.
    """
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
        soup.find(attrs={"role": "main"}),
        soup.find("div", {"id": re.compile("content|article|main|post|body|entry|markdown|rich", re.I)}),
        soup.find("div", {"class": re.compile("content|article|main|post|body|entry|markdown|rich", re.I)}),
        soup.find("section", {"id": re.compile("content|article|main|post|body|entry|markdown|rich", re.I)}),
        soup.find("section", {"class": re.compile("content|article|main|post|body|entry|markdown|rich", re.I)})
    ]
    
    # Filter out None values
    potential_containers = [container for container in potential_containers if container]
    
    if potential_containers:
        # Find container with the most meaningful text density
        def container_score(container):
            paragraph_text = ''.join(p.get_text(separator=' ', strip=True) for p in container.find_all('p'))
            text_len = len(paragraph_text)
            link_text_len = sum(len(a.get_text(strip=True)) for a in container.find_all('a')) + 1
            # Prefer higher text, lower link density
            score = text_len / link_text_len
            # Slight boost if article/main tag
            if container.name in {"article", "main", "section"}:
                score *= 1.2
            return score

        most_content_container = max(potential_containers, key=container_score)
        content_elements.append(most_content_container)
    else:
        # If no specific containers found, use the body
        content_elements.append(soup.body)

    # Extract content from each element type
    all_content = []
    image_text_chunks = []
    
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

        # Extract tables as Markdown if enabled
        if SCRAPE_TABLES_AS_MARKDOWN:
            tables = container.find_all('table')
            for table in tables:
                md = _table_to_markdown(table)
                if md:
                    all_content.append(md)
    
    # Extract div content when it might contain important text not in paragraphs
    for container in content_elements:
        divs = container.find_all('div', recursive=False)
        for div in divs:
            # Check if div contains paragraphs or other structured content
            if not div.find_all(['p', 'ul', 'ol', 'h1', 'h2', 'h3', 'h4']):
                text = div.get_text(strip=True)
                if text and len(text) > 50:  # Only include substantial div content
                    all_content.append(text)
    
    # Attempt to extract JSON-LD articleBody if present (common on news/blogs)
    try:
        json_ld_texts = []
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.get_text(strip=True))
            except Exception:
                continue
            if isinstance(data, dict):
                data = [data]
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        body = item.get('articleBody') or item.get('description')
                        if body and isinstance(body, str) and len(body) > 100:
                            json_ld_texts.append(body)
        if json_ld_texts:
            all_content.extend(json_ld_texts)
    except Exception:
        pass

    # Image OCR/vision (optional)
    # Decide dynamically per-call; if not provided, fall back to env var (evaluated at runtime)
    _enable_images = enable_image_vision if enable_image_vision is not None else (os.environ.get('SCRAPE_ENABLE_IMAGE_VISION', 'false').lower() == 'true')
    if _enable_images and base_url:
        try:
            image_text_chunks = _extract_image_text_from_container(content_elements[0], base_url)
        except Exception as e:
            print(f"Image OCR step failed: {e}")

    # Join all content with appropriate spacing
    cleaned_text = "\n\n".join(all_content + (image_text_chunks or []))
    
    # Remove consecutive newlines and extra spaces
    cleaned_text = re.sub(r'\n{3,}', '\n\n', cleaned_text)
    cleaned_text = re.sub(r' {2,}', ' ', cleaned_text)
    
    print(f"Extracted content length: {len(cleaned_text)}")
    return cleaned_text if cleaned_text.strip() else "No relevant content found."


def _table_to_markdown(table_tag) -> str:
    """Convert an HTML <table> to GitHub-flavored Markdown string."""
    try:
        # Gather rows
        rows = []
        headers = []
        thead = table_tag.find('thead')
        if thead:
            for tr in thead.find_all('tr'):
                headers = [(_get_text_th(td)) for td in tr.find_all(['th', 'td'])]
                if headers:
                    break
        if not headers:
            first_tr = table_tag.find('tr')
            if first_tr:
                headers = [(_get_text_th(td)) for td in first_tr.find_all(['th', 'td'])]
        # Body rows
        for tr in table_tag.find_all('tr'):
            cells = [(_get_text_td(td)) for td in tr.find_all('td')]
            if cells:
                rows.append(cells)
        if not headers and not rows:
            return ''
        # Build markdown
        md_lines = []
        if headers:
            md_lines.append('| ' + ' | '.join(headers) + ' |')
            md_lines.append('| ' + ' | '.join(['---'] * len(headers)) + ' |')
        for r in rows:
            md_lines.append('| ' + ' | '.join(r) + ' |')
        return '\n'.join(md_lines)
    except Exception:
        return ''


def _get_text_th(tag) -> str:
    text = tag.get_text(separator=' ', strip=True)
    return text.replace('|', '\\|')


def _get_text_td(tag) -> str:
    text = tag.get_text(separator=' ', strip=True)
    return text.replace('|', '\\|')


def _extract_image_text_from_container(container, base_url: str):
    """Find key images in container, fetch them (size-limited), and run vision/OCR.

    Returns list of text blocks like "Image analysis: ..." limited by SCRAPE_IMAGE_MAX.
    """
    results = []
    if not container:
        return results

    # Defer import to avoid heavy deps in simple flows
    try:
        from models.ocr import analyze_image_with_vision_model
    except Exception as e:
        print(f"Vision OCR not available: {e}")
        return results

    # Choose candidate images: within main container, skip tiny icons and data URIs too large
    imgs = container.find_all('img')
    candidates = []
    for img in imgs:
        alt_text = (img.get('alt') or '').strip()
        src = img.get('src') or ''
        if not src:
            continue
        # Skip tracking pixels
        try:
            w = int(img.get('width') or 0)
            h = int(img.get('height') or 0)
            if (w and h) and (w * h < 8000):
                continue
        except Exception:
            pass
        candidates.append((src, alt_text))

    # Prioritize images that have alt text or likely diagrams/charts
    def score(item):
        src, alt = item
        s = 0
        if alt:
            s += 2
        if re.search(r'(diagram|chart|graph|table|figure|infographic)', alt.lower()):
            s += 3
        if re.search(r'(diagram|chart|graph|table|figure|infographic)', src.lower()):
            s += 2
        return -s  # sort ascending to get highest first with negative

    candidates.sort(key=score)
    processed = 0
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0'})
    for src, alt in candidates:
        if processed >= SCRAPE_IMAGE_MAX:
            break
        try:
            if src.startswith('data:'):
                # data URI
                comma_idx = src.find(',')
                if comma_idx == -1:
                    continue
                meta, b64 = src[:comma_idx], src[comma_idx+1:]
                if ';base64' not in meta:
                    continue
                data = base64.b64decode(b64)
                if len(data) > SCRAPE_IMAGE_MAX_BYTES:
                    continue
                with tempfile.NamedTemporaryFile(delete=False, suffix='.img') as tmp:
                    tmp.write(data)
                    tmp_path = tmp.name
            else:
                abs_url = urljoin(base_url, src)
                resp = session.get(abs_url, timeout=SCRAPE_REQUEST_TIMEOUT_SECONDS, stream=True)
                content_length = int(resp.headers.get('Content-Length') or 0)
                if content_length and content_length > SCRAPE_IMAGE_MAX_BYTES:
                    resp.close()
                    continue
                data = resp.content if not content_length else resp.raw.read(SCRAPE_IMAGE_MAX_BYTES + 1)
                if len(data) > SCRAPE_IMAGE_MAX_BYTES:
                    resp.close()
                    continue
                suffix = os.path.splitext(urlparse(abs_url).path)[1] or '.img'
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(data)
                    tmp_path = tmp.name
                resp.close()

            try:
                analysis = analyze_image_with_vision_model(tmp_path)
                prefix = f"Image analysis ({alt}):" if alt else "Image analysis:"
                results.append(f"{prefix}\n{analysis}")
                processed += 1
            finally:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
        except Exception as e:
            print(f"Failed to process image {src}: {e}")

    return results

def parse_content(content, question, lang: str = 'en'):
    """Use Ollama to generate an answer based on the scraped content.

    If image analysis blocks are present, prefer a vision-capable QA model.
    Models are configurable via env:
      - SCRAPE_QA_MODEL (default: 'mistral')
      - SCRAPE_QA_IMAGE_MODEL (default: VISION_MODEL or 'granite3.2-vision:latest')
    """
    # Split content into manageable chunks
    max_length = 6000
    chunks = [content[i:i + max_length] for i in range(0, len(content), max_length)]

    # Detect presence of image analysis sections (case-insensitive)
    contains_image_analysis = ('image analysis' in content.lower())

    # Choose model dynamically
    default_model = os.environ.get('SCRAPE_QA_MODEL', 'mistral')
    vision_default = os.environ.get('VISION_MODEL', 'granite3.2-vision:latest')
    image_model = os.environ.get('SCRAPE_QA_IMAGE_MODEL', vision_default)
    model_name = image_model if contains_image_analysis else default_model

    # If multiple chunks, use first chunk but inform about total content
    chunk_intro = f"This is part 1 of {len(chunks)} from the extracted content. " if len(chunks) > 1 else ""

    language_hint = f"Please answer in {lang}." if lang and lang.lower() != 'en' else ""
    guidance = "The content may include AI-generated image analysis; reason carefully about visuals described." if contains_image_analysis else ""
    prompt = f"""{chunk_intro}Based on the following content:

    {chunks[0]}

    Question: {question}

    {guidance}
    Provide a clear, well-structured explanation. If the content lacks the answer, say so.
    {language_hint}
    """

    try:
        response = ollama.chat(model=model_name, messages=[{"role": "user", "content": prompt}])
        return response['message']['content']
    except Exception as e:
        return f"Error generating response: {str(e)}"


def parse_content_with_model(content, question, lang: str = 'en'):
    """Return both the answer and the model selected for transparency."""
    max_length = 6000
    chunks = [content[i:i + max_length] for i in range(0, len(content), max_length)]
    contains_image_analysis = ('image analysis' in content.lower())
    default_model = os.environ.get('SCRAPE_QA_MODEL', 'mistral')
    vision_default = os.environ.get('VISION_MODEL', 'granite3.2-vision:latest')
    image_model = os.environ.get('SCRAPE_QA_IMAGE_MODEL', vision_default)
    # Allow override via env to force image model for testing
    if os.environ.get('SCRAPE_QA_FORCE_IMAGE_MODEL', 'false').lower() == 'true':
        contains_image_analysis = True
    model_name = image_model if contains_image_analysis else default_model

    chunk_intro = f"This is part 1 of {len(chunks)} from the extracted content. " if len(chunks) > 1 else ""
    language_hint = f"Please answer in {lang}." if lang and lang.lower() != 'en' else ""
    guidance = "The content may include AI-generated image analysis; reason carefully about visuals described." if contains_image_analysis else ""
    prompt = f"""{chunk_intro}Based on the following content:

    {chunks[0]}

    Question: {question}

    {guidance}
    Provide a clear, well-structured explanation. If the content lacks the answer, say so.
    {language_hint}
    """
    try:
        response = ollama.chat(model=model_name, messages=[{"role": "user", "content": prompt}])
        return {'answer': response['message']['content'], 'model': model_name}
    except Exception as e:
        return {'answer': f"Error generating response: {str(e)}", 'model': model_name}


# -----------------------------
# Intelligent Web Search
# -----------------------------

def _simple_rank(query: str, docs: list[dict]) -> list[dict]:
    """Rank docs by simple term frequency score for the query."""
    q_terms = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 2]
    scored = []
    for d in docs:
        text = (d.get('content') or '').lower()
        score = sum(text.count(t) for t in q_terms)
        d2 = d.copy()
        d2['score'] = score
        scored.append(d2)
    scored.sort(key=lambda x: x.get('score', 0), reverse=True)
    return scored


def _fetch_and_extract(url: str, include_images: bool = False) -> str:
    """Fetch a URL and extract readable content (PDF-aware)."""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36'
        }
        r = requests.get(url, headers=headers, timeout=SCRAPE_REQUEST_TIMEOUT_SECONDS, allow_redirects=True)
        ctype = (r.headers.get('Content-Type') or '').lower()
        if 'application/pdf' in ctype or url.lower().endswith('.pdf'):
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmpf:
                tmpf.write(r.content)
                path = tmpf.name
            try:
                # Use OCR pipeline with mode depending on include_images (vision usage)
                from models.ocr import extract_text_with_metadata
                mode = 'auto' if include_images else 'ocr_only'
                res = extract_text_with_metadata(path, mode=mode)
                return (res.get('text') or '')
            finally:
                try:
                    os.remove(path)
                except Exception:
                    pass
        html = r.text
        # Try main extractor, fallback to readability
        text = extract_body_content(html, base_url=url, enable_image_vision=include_images)
        if (not text) or len(text) < 100:
            text = extract_with_readability(html)
        return text or ''
    except Exception:
        return ''


# ---------- Text utils and ranking helpers ----------
_STOPWORDS = set([
    "a","an","and","the","is","are","was","were","be","been","being","am",
    "do","does","did","doing","have","has","had","having","of","to","in","on",
    "for","from","by","with","about","into","over","under","after","before",
    "during","between","without","within","as","at","than","then","so","such",
    "other","more","most","some","any","no","not","only","own","same","can",
    "will","just","don","should","now","or","if","but","because","until","while",
    "both","each","few","he","she","it","they","them","his","her","its","their",
    "you","your","we","our","i","me","my","mine","ours","yours","themselves",
    "himself","herself","itself","ourselves","yourselves"
])

def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    words = re.findall(r"\w+", text.lower())
    return [w for w in words if len(w) > 2 and w not in _STOPWORDS]

def _cosine_sim(vec_a: Dict[str, float], vec_b: Dict[str, float]) -> float:
    if not vec_a or not vec_b:
        return 0.0
    dot = 0.0
    for k, va in vec_a.items():
        vb = vec_b.get(k)
        if vb:
            dot += va * vb
    na = sum(v*v for v in vec_a.values()) ** 0.5 or 1.0
    nb = sum(v*v for v in vec_b.values()) ** 0.5 or 1.0
    return float(dot / (na * nb))

def _tfidf_rank(query: str, docs: list[dict]) -> list[dict]:
    tokens_docs = [ _tokenize(d.get('content') or '') for d in docs ]
    q_tokens = _tokenize(query)
    N = len(docs) or 1
    # DF
    df: Dict[str,int] = {}
    for toks in tokens_docs:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    # IDF
    idf: Dict[str,float] = {}
    for t, c in df.items():
        idf[t] = 1.0 + float(__import__('math').log((N + 1) / (c + 1)))
    # Build vectors
    def tfidf_vec(toks: List[str]) -> Dict[str,float]:
        tf: Dict[str,int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        return { t: (tf[t] * idf.get(t, 0.0)) for t in tf }
    q_vec = tfidf_vec(q_tokens)
    ranked = []
    for d, toks in zip(docs, tokens_docs):
        v = tfidf_vec(toks)
        score = _cosine_sim(q_vec, v)
        dd = d.copy()
        dd['score'] = score
        ranked.append(dd)
    ranked.sort(key=lambda x: x.get('score', 0.0), reverse=True)
    return ranked

def _bm25_rank(query: str, docs: list[dict], k1: float = 1.5, b: float = 0.75) -> list[dict]:
    import math
    doc_tokens = [ _tokenize(d.get('content') or '') for d in docs ]
    q_terms = _tokenize(query)
    N = len(docs) or 1
    # DF
    df: Dict[str,int] = {}
    for toks in doc_tokens:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    idf = { t: math.log( (N - c + 0.5) / (c + 0.5) + 1.0 ) for t, c in df.items() }
    avgdl = sum(len(toks) for toks in doc_tokens) / N
    def score_doc(toks: list[str]) -> float:
        import collections
        tf = collections.Counter(toks)
        dl = len(toks) or 1
        score = 0.0
        for t in q_terms:
            f = tf.get(t, 0)
            if f == 0:
                continue
            idf_t = idf.get(t, 0.0)
            denom = f + k1 * (1 - b + b * (dl / (avgdl or 1.0)))
            score += idf_t * ( (f * (k1 + 1)) / denom )
        return float(score)
    ranked = []
    for d, toks in zip(docs, doc_tokens):
        dd = d.copy()
        dd['score'] = score_doc(toks)
        ranked.append(dd)
    ranked.sort(key=lambda x: x.get('score', 0.0), reverse=True)
    return ranked

def _embed_text(text: str) -> Optional[List[float]]:
    try:
        model = os.environ.get('EMBED_MODEL', 'nomic-embed-text')
        if not model:
            return None
        # truncate to keep prompt small
        snippet = (text or '')[:2000]
        res = ollama.embeddings(model=model, prompt=snippet)
        return res.get('embedding')
    except Exception as e:
        print(f"Embedding failed: {e}")
        return None

def _embed_rank(query: str, docs: list[dict]) -> list[dict]:
    import math
    qv = _embed_text(query)
    if not qv:
        return _tfidf_rank(query, docs)
    def cosine(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x*y for x,y in zip(a,b))
        na = math.sqrt(sum(x*x for x in a)) or 1.0
        nb = math.sqrt(sum(y*y for y in b)) or 1.0
        return float(dot / (na * nb))
    ranked = []
    for d in docs:
        dv = _embed_text(d.get('content') or '')
        score = cosine(qv, dv) if dv else 0.0
        dd = d.copy()
        dd['score'] = score
        ranked.append(dd)
    ranked.sort(key=lambda x: x.get('score', 0.0), reverse=True)
    return ranked

def _rank_docs(query: str, docs: list[dict]) -> list[dict]:
    method = (os.environ.get('INTEL_RANKER') or 'tfidf').strip().lower()
    if method == 'bm25':
        return _bm25_rank(query, docs)
    if method == 'embed':
        return _embed_rank(query, docs)
    if method == 'simple':
        return _simple_rank(query, docs)
    return _tfidf_rank(query, docs)

def _add_ui_similarity(ranked: list[dict]) -> list[dict]:
    # Map raw scores to a compressed UI band ~[0.8, 0.95] using percentile rank
    if not ranked:
        return ranked
    scores = [d.get('score') or 0.0 for d in ranked]
    sorted_scores = sorted(scores)
    def percentile(s: float) -> float:
        # fraction of scores less than or equal
        count = 0
        for v in sorted_scores:
            if v <= s:
                count += 1
        p = count / len(sorted_scores)
        return 0.8 + p * (0.95 - 0.8)
    for d in ranked:
        d['uiSimilarity'] = round(percentile(float(d.get('score') or 0.0)), 3)
    return ranked

def synthesize_answer_with_citations(query: str, docs: list[dict], lang: str = 'en') -> dict:
    """Use LLM to synthesize an answer with inline citations [n] and a sources list."""
    if not docs:
        return {'answer': 'No relevant sources found.', 'sources': []}
    # Build context with numbered sources
    context_parts = []
    sources = []
    for idx, d in enumerate(docs, start=1):
        title = d.get('title') or d.get('url')
        snippet = (d.get('snippet') or d.get('content') or '')[:2000]
        context_parts.append(f"[Source {idx}] {title}\nURL: {d.get('url')}\n---\n{snippet}")
        src_obj = {'index': idx, 'title': title, 'url': d.get('url')}
        if d.get('snippet'):
            src_obj['snippet'] = d.get('snippet')
        if d.get('score') is not None:
            src_obj['similarity'] = round(float(d.get('score')), 4)
        if d.get('uiSimilarity') is not None:
            src_obj['uiSimilarity'] = float(d.get('uiSimilarity'))
        if d.get('llmSim') is not None:
            src_obj['llmSimilarity'] = float(d.get('llmSim'))
        sources.append(src_obj)
    context = "\n\n".join(context_parts)

    default_model = os.environ.get('SCRAPE_QA_MODEL', 'mistral')
    language_hint = f"Please answer in {lang}." if lang and lang.lower() != 'en' else ''
    prompt = f"""
You are an educational assistant. Using the sources below, answer the query clearly and concisely for a student audience. Use inline citations like [1], [2] when statements come from a source. If uncertain, say so.

Query: {query}

Sources:
{context}

Instructions:
- Provide a brief, structured answer optimized for learning.
- Use bullet points or short paragraphs.
- Include inline citations [n] after claims.
- End with 2-3 suggested follow-up study prompts.
{language_hint}
"""
    try:
        resp = ollama.chat(model=default_model, messages=[{"role": "user", "content": prompt}])
        answer = resp['message']['content']
    except Exception as e:
        answer = f"Error generating answer: {str(e)}"
    return {'answer': answer, 'sources': sources}


def intelligent_web_search(query: str, max_results: int = 5, lang: str = 'en', include_images: bool = False) -> dict:
    """End-to-end: search, fetch, rank (TF+optional LLM), and synthesize with citations."""
    fetch_n = max(max_results, 10)
    results = search_google(query, max_results=fetch_n)
    if isinstance(results, dict) and results.get('error'):
        return {'error': results['error']}
    # Fetch and extract
    docs = []
    for r in (results or [])[:fetch_n]:
        url = r.get('url')
        if not url:
            continue
        content = _fetch_and_extract(url, include_images=include_images)
        if not content:
            continue
        snippet = _make_snippet(content, query)
        docs.append({'title': r.get('title'), 'url': url, 'content': content, 'snippet': snippet})
    if not docs:
        return {'answer': 'No content could be extracted from the top results.', 'sources': []}
    # Rank and select top k
    ranked = _rank_docs(query, docs)
    ranked = _add_ui_similarity(ranked)
    if os.environ.get('INTEL_RERANK', 'true').lower() == 'true':
        try:
            ranked = _llm_rerank(query, ranked[:10]) + ranked[10:]
        except Exception as e:
            print(f"LLM rerank failed: {e}")
    top_docs = ranked[:min(len(ranked), max_results)]
    return synthesize_answer_with_citations(query, top_docs, lang=lang)

def search_with_similarity(query: str, max_results: int = 5, include_images: bool = False) -> list[dict]:
    """Search and return results enriched with similarity score and snippet."""
    fetch_n = max(max_results, 10)
    results = search_google(query, max_results=fetch_n)
    if isinstance(results, dict) and results.get('error'):
        return []
    docs = []
    for r in (results or [])[:fetch_n]:
        url = r.get('url')
        if not url:
            continue
        content = _fetch_and_extract(url, include_images=include_images)
        if not content:
            continue
        snippet = _make_snippet(content, query)
        docs.append({'title': r.get('title'), 'url': url, 'content': content, 'snippet': snippet})
    if not docs:
        return []
    ranked = _rank_docs(query, docs)
    ranked = _add_ui_similarity(ranked)
    top = ranked[:max_results]
    # Project fields for API
    projected = []
    for d in top:
        projected.append({
            'title': d.get('title'),
            'url': d.get('url'),
            'snippet': d.get('snippet') or _make_snippet(d.get('content') or '', query),
            'similarity': round(float(d.get('score') or 0), 4),
            'uiSimilarity': d.get('uiSimilarity')
        })
    return projected

def _make_snippet(content: str, query: str, window: int = 220) -> str:
    if not content:
        return ''
    terms = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 2]
    text = re.sub(r"\s+", " ", content)
    lower = text.lower()
    for t in terms:
        idx = lower.find(t)
        if idx != -1:
            start = max(0, idx - window//2)
            end = min(len(text), idx + window//2)
            snippet = text[start:end].strip()
            return ("... " + snippet + " ...") if start > 0 or end < len(text) else snippet
    return text[:window].strip() + (" ..." if len(text) > window else '')

def _similarity_rank(query: str, docs: list[dict]) -> list[dict]:
    q_terms = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 2]
    if not q_terms:
        return _simple_rank(query, docs)
    def vec(text: str) -> dict:
        counts = {}
        for w in re.findall(r"\w+", text.lower()):
            if len(w) <= 2:
                continue
            counts[w] = counts.get(w, 0) + 1
        return counts
    qv = vec(" ".join(q_terms))
    qnorm = max(1.0, sum(v*v for v in qv.values()) ** 0.5)
    ranked = []
    for d in docs:
        tv = vec(d.get('content') or '')
        dot = sum(qv.get(w, 0) * tv.get(w, 0) for w in qv.keys())
        vnorm = max(1.0, sum(v*v for v in tv.values()) ** 0.5)
        score = dot / (qnorm * vnorm)
        d2 = d.copy()
        d2['score'] = float(score)
        ranked.append(d2)
    ranked.sort(key=lambda x: x.get('score', 0.0), reverse=True)
    return ranked

def _llm_rerank(query: str, docs: list[dict]) -> list[dict]:
    items = []
    for i, d in enumerate(docs, start=1):
        items.append({
            'index': i,
            'title': d.get('title'),
            'url': d.get('url'),
            'snippet': (d.get('snippet') or d.get('content') or '')[:500]
        })
    instruction = {
        'task': 'rerank',
        'query': query,
        'items': items,
        'output_format': {
            'ranking': [{'index': 'int from items', 'similarity': 'float 0..1, higher is better'}]
        }
    }
    prompt = (
        "You are a helpful educational search assistant. Given a user query and a list of sources, "
        "rerank the sources by relevance to the query and assign a similarity score between 0 and 1. "
        "Respond ONLY with JSON matching the specified output_format.\n\n" + json.dumps(instruction)
    )
    try:
        resp = ollama.chat(model=os.environ.get('SCRAPE_QA_MODEL', 'mistral'), messages=[{"role": "user", "content": prompt}])
        content = resp['message']['content']
        data = json.loads(content)
        order = data.get('ranking') or []
        idx_to_doc = {i+1: d for i, d in enumerate(docs)}
        new_docs = []
        seen = set()
        for item in order:
            idx = int(item.get('index', 0))
            sim = float(item.get('similarity', 0))
            if idx in idx_to_doc and idx not in seen:
                d = idx_to_doc[idx].copy()
                # Preserve original ranker score; store LLM score separately
                d['llmSim'] = sim
                new_docs.append(d)
                seen.add(idx)
        for i, d in enumerate(docs, start=1):
            if i not in seen:
                new_docs.append(d)
        return new_docs
    except Exception as e:
        print(f"LLM rerank parse error: {e}")
        return docs