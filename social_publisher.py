import os
import requests
import logging
import base64

logger = logging.getLogger(__name__)

def publish_to_instagram(content_text: str, image_url: str) -> bool:
    """
    Publishes an image and caption to Instagram using the Facebook Graph API.
    Process: 
    1. Create a media container (upload image).
    2. Publish the container.
    """
    access_token = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
    account_id = os.environ.get("INSTAGRAM_ACCOUNT_ID")
    
    if not access_token or not account_id:
        logger.error("Instagram credentials missing.")
        return False
        
    try:
        # Step 1: Create media container
        container_url = f"https://graph.facebook.com/v19.0/{account_id}/media"
        container_payload = {
            "image_url": image_url,
            "caption": content_text,
            "access_token": access_token
        }
        
        container_response = requests.post(container_url, data=container_payload)
        container_response.raise_for_status()
        container_data = container_response.json()
        creation_id = container_data.get("id")
        
        if not creation_id:
            logger.error(f"Failed to create Instagram media container: {container_data}")
            return False
            
        # Step 2: Publish the container
        publish_url = f"https://graph.facebook.com/v19.0/{account_id}/media_publish"
        publish_payload = {
            "creation_id": creation_id,
            "access_token": access_token
        }
        
        publish_response = requests.post(publish_url, data=publish_payload)
        publish_response.raise_for_status()
        publish_data = publish_response.json()
        
        if "id" in publish_data:
            logger.info(f"Successfully published to Instagram. Post ID: {publish_data['id']}")
            return True
        else:
            logger.error(f"Failed to publish Instagram media: {publish_data}")
            return False
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Instagram API Error: {e}")
        if e.response is not None:
             logger.error(f"Response: {e.response.text}")
        return False

def publish_to_pinterest(content_text: str, image_url: str) -> bool:
    """
    Publishes a pin to Pinterest using the Pinterest API (v5).
    """
    access_token = os.environ.get("PINTEREST_ACCESS_TOKEN")
    board_id = os.environ.get("PINTEREST_BOARD_ID")
    
    if not access_token or not board_id:
        logger.error("Pinterest credentials missing.")
        return False
        
    try:
        url = "https://api.pinterest.com/v5/pins"
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        with open(image_url, 'rb') as img_file:
            image_data = img_file.read()
            encoded_image = base64.b64encode(image_data).decode('utf-8')
            
        payload = {
            "board_id": board_id,
            "media_source": {
                "source_type": "image_base64",
                "content_type": "image/jpeg",
                "data": encoded_image
            },
            "description": content_text,
            "title": content_text[:100], # type: ignore # Pinterest titles have a max length
        }
        
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        
        data = response.json()
        logger.info(f"Successfully published to Pinterest. Pin ID: {data.get('id')}")
        
        try:
            os.remove(image_url)
            logger.info(f"Cleaned up local image file: {image_url}")
        except Exception as e:
            logger.warning(f"Failed to cleanup local image file {image_url}: {e}")
            
        return True
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Pinterest API Error: {e}")
        print(f"\n--- PINTEREST PUBLISHING FAILED ---")
        print(f"Error: {e}")
        if e.response is not None:
            logger.error(f"Response: {e.response.text}")
            print(f"Status Code: {e.response.status_code}")
            
            if e.response.status_code == 401:
                bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
                admin_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "5593682924")
                if bot_token:
                    try:
                        requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", data={
                            "chat_id": admin_chat_id,
                            "text": "Pinterest token has expired! Please regenerate your token."
                        })
                    except Exception as err:
                        logger.error(f"Failed to send Telegram alert for Pinterest token expiry: {err}")
            
            try:
                print(f"API Response JSON: {e.response.json()}")
            except ValueError:
                print(f"API Response Text: {e.response.text}")
        print(f"-----------------------------------\n")
        return False
