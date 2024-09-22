
import time
import os
import pandas as pd
from openai import OpenAI
import base64
import re
import logging

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError




# ssh key stored in .ssh directory
# Enter the instance through terminal: ssh macke@34.28.119.141
# activate virtual environment: source ~/myenv/bin/activate

df = pd.read_csv("qna.camp_mail.csv")

client = OpenAI(api_key = "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")


logging.basicConfig(
    filename='/home/macke/email_bot.log',  # Log file path
    level=logging.INFO,  # Logging level (can be DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format='%(asctime)s - %(levelname)s - %(message)s',  # Log format
)


logging.info("Script Running")


SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/gmail.labels'
]

def load_service_account_credentials():
    creds = service_account.Credentials.from_service_account_file(
        'credentials.json', scopes=SCOPES)
    return creds


def get_email_body(msg):
    """Extracts the body from the email message."""
    if 'data' in msg['payload']['body']:
        body_data = msg['payload']['body']['data']
        body = base64.urlsafe_b64decode(body_data.encode('ASCII')).decode('utf-8')
    else:
        parts = msg['payload'].get('parts', [])
        for part in parts:
            if part['mimeType'] == 'text/plain':
                body_data = part['body']['data']
                body = base64.urlsafe_b64decode(body_data.encode('ASCII')).decode('utf-8')
                return body
    return body

def clean_email_body(body):
    
    body = re.sub(r'On.*\n.*wrote:.*', '', body)
    body = body.strip()

    return body

def get_response(query, df):

    logging.info(f'responding to query: {query}')

    # Generate a response using the AI with the context from the CSV
    context = "Use the following context to answer the query as accurately as possible:"
    for i, row in df.iterrows():
        context += f"\nQ: {row['Question']}\nA: {row['Answer']}"
    
    context += f"\nUser query: {query}\nResponse:"

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",  # Use the appropriate model
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": context},
        ],
    )

    response_text = response.choices[0].message.content.strip()

    # Cleanup response text formatting
    response_text = response_text.replace('\n\n', '\n').replace('\n', ' ').strip()  # Cleanup newlines
    response_text = response_text.replace('  ', ' ')  # Remove any double spaces

    # Check for registration link insertion if relevant
    response_text = check_for_registration_query(query, response_text)
    
    # Calculate confidence score
    confidence = calculate_confidence(response_text, query.split())

    return response_text, confidence

    
def send_html_email(service, user_id, to_email, subject, body_text, in_reply_to=None, references=None):
    # Embed the local image if provided

    # Start building the HTML content
    html_content = f"""
    <html>
      <head>
        <style>
          body {{
            font-family: 'Roboto, Arial';
            line-height: 1.6;
            color: #333;
          }}
          h1 {{
            color: #006600;
          }}
          .content {{
            margin: 20px;
          }}
          .footer {{
            margin-top: 20px;
            padding-top: 10px;
            border-top: 1px solid #ccc;
            font-size: 0.9em;
          }}
          .footer a {{
            color: #0056b3;
            text-decoration: none;
          }}
          .disclaimer {{
            margin-top: 40px; 
            color: #999; 
            font-size: 0.7em; 
            font-style: italic; 
            text-align: left;
          }}
        </style>
      </head>
      <body>
        <div class="content">
          <h1>Hello,</h1>
          <p>{body_text}</p>
        </div>
        <div class="footer">
          <p>{add_footer_note()}</p>
        </div>
      </body>
    </html>
    """

    # Create MIME message
    message = MIMEMultipart("alternative")
    message["to"] = to_email
    message["subject"] = subject
    message.attach(MIMEText(html_content, "html"))

    # Add In-Reply-To and References headers to thread the email as a reply
    if in_reply_to:
        message.add_header("In-Reply-To", in_reply_to)
    if references:
        message.add_header("References", references)

    # Encode the message to base64 format
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

    # Create the request body for Gmail API
    message_body = {
        "raw": raw_message
    }

    try:
        # Send the email using the Gmail API
        message = service.users().messages().send(userId=user_id, body=message_body).execute()
        print(f"Message sent to {to_email} with Message Id: {message['id']}")
    except HttpError as error:
        print(f'An error occurred: {error}')

def add_footer_note():
    # HTML for the small, italicized note
    footer_note = """
    <div class="disclaimer">
        This message was generated by OpenAI 1.43.0. If there was an error, please contact <a href="mailto:mackthompson16@gmail.com" style="color: #999; text-decoration: none;">mackthompson16@gmail.com</a> to diagnose the issue.
    </div>
    """
    return footer_note

def check_for_registration_query(query, response_text):
    # Define keywords or phrases related to signing up or checking room availability
    signup_keywords = ["sign up", "register", "room", "availability", "spot", "join"]
    
    # Convert query to lower case for case-insensitive matching
    query_lower = query.lower()

    # Check if any of the keywords are in the query
    if any(keyword in query_lower for keyword in signup_keywords):
        # Remove any existing URLs (if the AI generated one) to avoid duplication
        response_text = re.sub(r'https?://\S+', '', response_text).strip()

        # Append the formatted registration form message and link to the response
        response_text += "<br><br>"
        response_text += '<strong style="font-size: 1.2em;"><a href="https://forms.gle/YvXQ58rELbWTukKQ7">Registration Form</a></strong>'
    
    return response_text

def calculate_confidence(response_text, keywords):
    """Simple heuristic to calculate confidence."""
    tokens = response_text.split()
    token_count = len(tokens)
    
    # Penalize responses that reference the database or apologize
    if "database" in response_text.lower() or "i apologize" in response_text.lower():
        return 0.0
    
    # Increase confidence if keywords are matched in the response
    keyword_match = any(keyword.lower() in response_text.lower() for keyword in keywords)
    
    # Basic token length heuristic
    confidence = min(1.0, token_count / 10.0)  # Adjust the divisor as needed
    if keyword_match:
        confidence += 0.1  # Boost confidence if a keyword matches
    
    return min(1.0, confidence)  # Ensure confidence is capped at 1.0


def contains_undesired_phrases(response_text):
    """
    Check if the response contains any undesired phrases such as references to a database.
    Returns True if such phrases are found, otherwise False.
    """
    undesired_phrases = [
        "database",    # Avoid mentioning the database
        "I apologize", # Avoid apologies
        "Unfortunately", # Avoid negative phrasing
        "I am not sure", # Avoid uncertain responses
        "query",
        "assist",
        "corresponding"

    ]
    
    
    for phrase in undesired_phrases:
        if phrase in response_text:
            return True
    return False

def main():
    creds = load_service_account_credentials()
    service = build('gmail', 'v1', credentials=creds)

    while True:
        try:
            results = service.users().messages().list(userId='me', labelIds=['INBOX'], q="is:unread").execute()
            messages = results.get('messages', [])

            if not messages:
                print("No new messages.")
            else:
                for message in messages:

                    msg = service.users().messages().get(userId='me', id=message['id']).execute()
                    headers = msg['payload']['headers']
                    for header in headers:
                        if header['name'] == 'From':
                            sender_email = header['value']
                            break
                    query = msg['snippet']  # You might want to extract the full body here
                    response, confidence = get_response(query, df)

                    # Only send the response if the confidence is 0.8 (80%) or higher
                    if confidence >= 0.8 and not contains_undesired_phrases(response):
                        send_html_email(service, 'me', sender_email, "Re: Your Query", response)
                    else:
                        print(f"Low confidence ({confidence * 100:.2f}%), or undesired phrase. not sending email.")

            time.sleep(60)  # Check for new emails every 60 seconds

        except HttpError as error:
            print(f'An error occurred: {error}')
            break

if __name__ == '__main__':
    main()

