import os
import logging
import urllib.parse
import time
import uuid
import random
import groq
import requests

logger = logging.getLogger(__name__)

# Configure the library
# We expect the caller or main.py to call configure(), but we can do it here lazily
_client = None

def _ensure_configured():
    global _client
    if _client is None:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable not set.")
        _client = groq.Groq(api_key=api_key)

def generate_topic_prompt() -> str:
    """
    Asks Gemini to brainstorm a creative topic for a social media post.
    """
    _ensure_configured()
    
    # Using Groq llama-3.3-70b-versatile with system instruction
    system_instruction = "You are a fashion content creator. You must ONLY generate content about fashion, style, outfits, clothing, accessories, and beauty. Never generate content about technology, AI, or any other topic."
    
    prompt = (
        "You are an expert social media manager and high-end fashion influencer. "
        "Strictly generate a single, highly specific and detailed trending content idea/topic "
        "for a premium fashion social media post (e.g., Instagram/Pinterest). "
        "All content MUST be strictly about fashion — topics should cover outfit ideas, style trends, "
        "clothing, accessories, beauty, street style, editorial looks, or seasonal fashion. Never generate anything outside of fashion. "
        "Do not use generic topics like 'summer fashion'. Instead, make it specific, e.g., 'effortless street style looks for hot summer days featuring linen co-ords and minimalist accessories'. "
        "Just reply with the topic idea, nothing else. Overall quality must be premium."
    )
    
    for attempt in range(2):
        try:
            assert _client is not None
            response = _client.chat.completions.create(
                model='llama-3.3-70b-versatile',
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt}
                ]
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            if attempt == 0:
                logger.error(f"Error generating topic, retrying in 5s: {e}")
                time.sleep(5)
            else:
                logger.error(f"Error generating topic on retry: {e}")
                
    return "Effortless minimalist street style outfit ideas" # Fallback

def generate_content(topic: str) -> dict:
    """
    Takes a topic and generates a caption and a visual idea.
    Returns a dict with 'caption' and 'image_prompt'.
    """
    _ensure_configured()
    
    system_instruction = "You are a fashion content creator. You must ONLY generate content about fashion, style, outfits, clothing, accessories, and beauty. Never generate content about technology, AI, or any other topic."
    
    prompt = f"""
    Based on the topic: "{topic}", create a highly engaging social media post.
    You are a premium fashion influencer with a vibrant, authentic personality.
    All content must be strictly about fashion or style. Overall quality must be premium — every generation should look and feel like it came from a professional fashion brand account.
    
    Provide the response in the following exact format:
    
    CAPTION:
    [The post caption. It must be at least 3-4 sentences long, sound completely natural and human, and be written like a real fashion influencer with personality. It must NEVER sound like AI wrote it. Always include relevant fashion, style, and high-reach hashtags. Add appropriate emojis.]
    
    IMAGE_PROMPT:
    [A highly descriptive, cinematic prompt that can be fed into an AI image generator to create the perfect companion image. You MUST always mention lighting, setting, outfit details, colors, mood, and camera style. For example: 'A stunning photorealistic fashion editorial, a young woman wearing an oversized beige linen blazer with wide leg trousers, golden hour sunlight, busy city street background, shot on Canon 5D, magazine quality, highly detailed'. Always aim for premium quality visual descriptions.]
    """
    
    for attempt in range(2):
        try:
            assert _client is not None
            response = _client.chat.completions.create(
                model='llama-3.3-70b-versatile',
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt}
                ]
            )
            text = response.choices[0].message.content
            
            # Parse the response
            caption_part = ""
            image_prompt_part = ""
            
            if "CAPTION:" in text and "IMAGE_PROMPT:" in text:
                parts = text.split("IMAGE_PROMPT:")
                caption_part = parts[0].replace("CAPTION:", "").strip()
                image_prompt_part = parts[1].strip()
            else:
                caption_part = text
                image_prompt_part = f"A high quality aesthetic image representing: {topic}"
                
            return {
                "caption": caption_part,
                "image_prompt": image_prompt_part
            }
            
        except Exception as e:
            if attempt == 0:
                logger.error(f"Error generating content, retrying in 5s: {e}")
                time.sleep(5)
            else:
                logger.error(f"Error generating content on retry: {e}")
                break
                
    return {
        "caption": f"Exploring the incredible world of {topic}! ✨ What are your thoughts? #trending #explore",
        "image_prompt": f"A beautiful cinematic and highly detailed image about {topic}"
    }

def generate_image(prompt):
    """
    Generates an image using Hugging Face FLUX.1-schnell model.
    """
    try:
        if not prompt or prompt.strip() == "":
            prompt = 'cinematic high fashion editorial photography, elegant model, luxury outfit, studio lighting, vogue magazine style'
            
        logger.info("Using Hugging Face FLUX.1-dev for image generation...")
        url = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-dev"
        hf_token = os.environ.get("HF_TOKEN")
        
        if not hf_token:
            logger.error("HF_TOKEN not found in environment.")
            return None
            
        headers = {
            "Authorization": f"Bearer {hf_token}"
        }
        
        payload = {
            "inputs": prompt,
            "parameters": {
                "seed": random.randint(1, 9999999),
                "num_inference_steps": 50,
                "guidance_scale": 7.5,
                "width": 1024,
                "height": 1024
            }
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        
        if response.status_code == 200:
            uuid_str = str(uuid.uuid4()).replace('-', '')
            filename = f"generated_{uuid_str[:8]}.jpg"
            save_dir = "D:/Content AI/generated_images"
            os.makedirs(save_dir, exist_ok=True)
            filepath = os.path.join(save_dir, filename)
            with open(filepath, "wb") as f:
                f.write(response.content)
            logger.info("Hugging Face image downloaded successfully.")
            return filepath
        else:
            logger.error(f"Failed to generate HF image: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"Image generation error: {e}")
        return None
