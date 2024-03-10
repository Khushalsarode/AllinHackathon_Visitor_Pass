"""Python Flask WebApp Auth0 integration example
"""

import json
from os import environ as env
from urllib.parse import quote_plus, urlencode

from authlib.integrations.flask_client import OAuth
from dotenv import find_dotenv, load_dotenv
from flask import Flask, redirect, send_from_directory, send_file, render_template, session,flash, url_for, request
from datetime import datetime, date
from werkzeug.exceptions import BadRequestKeyError  # Import BadRequestKeyError
from io import BytesIO
from pymongo import MongoClient
import qrcode
import uuid
import os
import tempfile
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition




ENV_FILE = find_dotenv()
if ENV_FILE:
    load_dotenv(ENV_FILE)

app = Flask(__name__)
app.secret_key = env.get("APP_SECRET_KEY")

# Connect to MongoDB
client = MongoClient('MongoUrl')
db = client['visitor_cards']
collection = db['cards']

# Directory to store images
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure the upload folder exists
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)



oauth = OAuth(app)

oauth.register(
    "auth0",
    client_id=env.get("AUTH0_CLIENT_ID"),
    client_secret=env.get("AUTH0_CLIENT_SECRET"),
    client_kwargs={
        "scope": "openid profile email",
    },
    server_metadata_url=f'https://{env.get("AUTH0_DOMAIN")}/.well-known/openid-configuration',
)


# Controllers API
@app.route("/")
def home():
    return render_template(
        "home.html",
        session=session.get("user"),
        pretty=json.dumps(session.get("user"), indent=4),
    )
    print(session.userinfo.nickname)



@app.route("/callback", methods=["GET", "POST"])
def callback():
    token = oauth.auth0.authorize_access_token()
    session["user"] = token
    return redirect("/")


@app.route("/login")
def login():
    return oauth.auth0.authorize_redirect(
        redirect_uri=url_for("callback", _external=True)
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(
        "https://"
        + env.get("AUTH0_DOMAIN")
        + "/v2/logout?"
        + urlencode(
            {
                "returnTo": url_for("home", _external=True),
                "client_id": env.get("AUTH0_CLIENT_ID"),
            },
            quote_via=quote_plus,
        )
    )


@app.route("/about")
def about():
    return render_template("about.html")

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/generate_card', methods=['POST','GET'])
def generate_card():
    if request.method == 'POST':
        try:
            # Get form data
            company_name = request.form['company_name']
            visitor_name = request.form['visitor_name']
            contact = request.form['contact']
            email = request.form['email']

            # Check if all required fields are filled
            if not (company_name and visitor_name and contact and email):
                raise BadRequestKeyError

            # Generate unique pass ID number
            pass_id = str(uuid.uuid4().hex)[:6]  # Generate a random hex string and take the first 6 characters
            # Textual month, day and year
            today = date.today()

            current_date = today.strftime("%B %d, %Y")

            # Save company logo image
            company_logo = request.files['company_logo']
            logo_filename = f'{pass_id}_logo.png'
            logo_path = os.path.join(app.config['UPLOAD_FOLDER'], logo_filename)
            company_logo.save(logo_path)

            # Create QR code with link to access the visitor card
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(f'http://visipasstech.co/visitor_card/{pass_id}')  # Replace 'yourwebsite.com' with your actual website domain
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white")
            qr_filename = f'{pass_id}_qr.png'
            qr_path = os.path.join(app.config['UPLOAD_FOLDER'], qr_filename)
            qr_img.save(qr_path)

            # Store form data and image paths in MongoDB
            card_data = {
                'pass_id': pass_id,
                'company_name': company_name,
                'visitor_name': visitor_name,
                'contact': contact,
                'email': email,
                'company_logo_path': logo_path.replace('\\', '/'), 
                'qr_code_path': qr_path.replace('\\', '/'),
                'date_generated': current_date

            }
            collection.insert_one(card_data)
            # Send email (you'll need to implement this part)
            #send_email(email, pass_id)  # Assuming you have a function to send emails
            #generate card and send it to usermail:
                        # Send email with the visitor card
            send_visitor_card_email(card_data)

            flash('Visitor card generated successfully and sent via email!', 'success')
            return render_template("generate_card.html")
        except BadRequestKeyError:
            flash('Please fill in all the required fields!', 'error')
            return render_template("generate_card.html")
        except Exception as e:
            flash(f'An error occurred: {str(e)}', 'error')
            return render_template("generate_card.html")
    return render_template("generate_card.html")

def send_visitor_card_email(card_data):
    try:
        # Render the visitor card HTML
        card_html = render_template('visitor_card_template.html', card_data=card_data)

        # Send the visitor card via SendGrid
        message = Mail(
            from_email='khushalsarode.in@gmail.com',  # Replace with your email address
            to_emails=card_data['email'],  # Visitor's email address
            subject='Your Visitor Card',
            html_content=card_html
        )

        sg = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))  # Get your SendGrid API key from environment variable
        response = sg.send(message)

        # Print the response for debugging
        print(response.status_code)
        print(response.body)
        print(response.headers)

        return 'Visitor card sent successfully.'
    except Exception as e:
        return f'Error sending visitor card via SendGrid: {str(e)}'


@app.route('/visitor_card/<pass_id>')
def generate_visitor_card(pass_id):
    # Retrieve card data from the database based on pass_id
    card_data = collection.find_one({'pass_id': pass_id})

    if card_data:
        # Render the template with the card data
        return render_template('visitor_card_template.html', card_data=card_data)
    else:
        return 'Visitor card not found.'



@app.route('/records')
def display_records():
    # Fetch all records from the collection
    records = list(collection.find())

    # Modify the image paths to be accessible via Flask's route
    for record in records:
        # Extract pass_id from the record
        pass_id = record['pass_id']

        # Construct the file paths for the images
        record['company_logo_path'] = f'/uploads/{pass_id}_logo.png'
        record['qr_code_path'] = f'/uploads/{pass_id}_qr.png'

    return render_template('records.html', records=records)

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True,port=env.get("PORT", 3000))
