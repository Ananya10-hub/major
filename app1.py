from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import random
import json
import pickle
import numpy as np
import nltk
from keras.models import load_model
import tensorflow as tf
from tensorflow.keras.preprocessing import image
from vc_ass import read_out_report_from_html
import os
import fitz  # Import PyMuPDF for PDF handling
from pdf import create_pdf  # Import the create_pdf function

nltk.download('punkt')
from nltk.stem import WordNetLemmatizer

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# SQLite Database Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
db = SQLAlchemy(app)

# User model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), nullable=False, unique=True)
    email = db.Column(db.String(150), nullable=False, unique=True)
    password = db.Column(db.String(150), nullable=False)

# Load the chatbot model and data
lemmatizer = WordNetLemmatizer()
intents = json.loads(open(r"C:\Users\Ananya\Desktop\major_prjct\intents.json").read())
words = pickle.load(open('words.pkl', 'rb'))
classes = pickle.load(open('classes.pkl', 'rb'))
model = load_model('chatbot_model.h5')

# Load the lung cancer prediction model
lung_cancer_model = tf.keras.models.load_model('custom_resnet_lung_model.keras')

def clean_up_sentence(sentence):
    """Tokenize and lemmatize the input sentence."""
    sentence_words = nltk.word_tokenize(sentence)
    sentence_words = [lemmatizer.lemmatize(word) for word in sentence_words]
    return sentence_words

def bag_of_words(sentence):
    """Create a bag of words representation for the input sentence."""
    sentence_words = clean_up_sentence(sentence)
    bag = [0] * len(words)
    for w in sentence_words:
        for i, word in enumerate(words):
            if word == w:
                bag[i] = 1
    return np.array(bag)

def predict_class(sentence):
    """Predict the class of the input sentence."""
    bow = bag_of_words(sentence)
    res = model.predict(np.array([bow]))[0]
    ERROR_THRESHOLD = 0.25
    results = [[i, r] for i, r in enumerate(res) if r > ERROR_THRESHOLD]

    results.sort(key=lambda x: x[1], reverse=True)
    return_list = []
    for r in results:
        return_list.append({'intent': classes[r[0]], 'probability': str(r[1])})
    return return_list

def get_response(intents_list, intents_json):
    """Get a random response for the predicted intent."""
    tag = intents_list[0]['intent']
    list_of_intents = intents_json['intents']
    for i in list_of_intents:
        if i['tags'][0] == tag:
            result = random.choice(i['responses'])
            break
    return result

# Function to load and preprocess an image
def load_and_preprocess_image(img_path, img_height=128, img_width=128):
    img = image.load_img(img_path, target_size=(img_height, img_width))
    img_array = image.img_to_array(img)
    img_array = np.expand_dims(img_array, axis=0)  # Add batch dimension
    img_array = img_array / 255.0  # Rescale the image
    return img_array

# Function to predict the lung cancer class
def predict_lung_cancer(img_path):
    img_array = load_and_preprocess_image(img_path)
    prediction = lung_cancer_model.predict(img_array)
    predicted_class = np.argmax(prediction, axis=1)[0]
    class_names = ['Lung Adenocarcinoma', 'Lung Benign Tissue', 'Lung Squamous Cell Carcinoma']
    return class_names[predicted_class]

def extract_text_from_pdf(pdf_path):
    """Extracts text content from each page of a PDF file."""
    text_content = ""
    with fitz.open(pdf_path) as pdf:
        for page_num in range(len(pdf)):
            page = pdf[page_num]
            text_content += page.get_text()
    return text_content

# Route for home page
@app.route('/')
def index():
    return render_template('home.html')

# Login/Signup page route
@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/dash')
def dash_page():
    return render_template('dash.html')

@app.route('/bot')
def bot_page():
    return render_template('bot.html')

@app.route('/report')
def report_page():
    return render_template('report.html')

# Signup route
@app.route('/signup', methods=['POST'])
def signup():
    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')

    # Check if email already exists
    user = User.query.filter_by(email=email).first()
    if user:
        flash('Email address already exists', 'error')
        return redirect(url_for('login_page'))

    # Hash password
    hashed_password = generate_password_hash(password, method='sha256')

    # Create new user
    new_user = User(username=username, email=email, password=hashed_password)
    db.session.add(new_user)
    db.session.commit()

    flash('Account created successfully', 'success')
    return redirect(url_for('login_page'))

# Login route
@app.route('/login', methods=['POST'])
def login():
    email = request.form.get('email')
    password = request.form.get('password')

    # Query user by email
    user = User.query.filter_by(email=email).first()

    if not user or not check_password_hash(user.password, password):
        flash('Invalid email or password', 'error')
        return redirect(url_for('login_page'))

    session['user_id'] = user.id
    session['username'] = user.username

    flash('Login successful', 'success')
    return redirect(url_for('dashboard'))

# Dashboard (after login)
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        flash('Please login to access this page', 'error')
        return redirect(url_for('login_page'))
    return render_template('dashboard.html', username=session['username'])

# Logout route
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    flash('Logged out successfully', 'success')
    return redirect(url_for('index'))

# Chatbot interaction route
@app.route('/chat', methods=['POST'])
def chat():
    """Handle chat messages from the user."""
    message = request.json['message']  # Expecting 'message' key
    ints = predict_class(message)
    res = get_response(ints, intents)
    return jsonify(res)  # Return response as JSON

# Upload and predict route
@app.route('/upload', methods=['POST', 'GET'])
def upload():
    if request.method == 'POST':
        if 'image' not in request.files:
            return 'No image found', 400
        image = request.files['image']
        if image.filename == '':
            return 'No image selected', 400
        if image:
            # Save the uploaded image
            image_path = os.path.join('uploads', image.filename)
            image.save(image_path)

            # Predict the lung cancer class
            prediction = predict_lung_cancer(image_path)

            # Map prediction to conditions
            if 'Adenocarcinoma' in prediction:
                stored_prediction = "aca"
            elif 'Benign Tissue' in prediction:
                stored_prediction = "normal"
            elif 'Squamous Cell Carcinoma' in prediction:
                stored_prediction = "scc"
            else:
                stored_prediction = "unknown"  # Handle unexpected cases

            # Create PDF based on the prediction
            pdf_file_path = create_pdf(stored_prediction)

            # Extract text from the created PDF
            extracted_text = extract_text_from_pdf(pdf_file_path)

            # Redirect to result page with extracted text
            return redirect(url_for('result', prediction=stored_prediction, image_filename=image.filename, pdf_file_path=pdf_file_path, report=extracted_text))
    elif request.method == 'GET':
        return render_template('report.html')

@app.route('/result')
def result():
    prediction = request.args.get('prediction')
    image_filename = request.args.get('image_filename')
    pdf_file_path = request.args.get('pdf_file_path')
    report = request.args.get('report')  # Get the extracted text from the PDF
    return render_template('result.html', prediction=prediction, image_filename=image_filename, pdf_file_path=pdf_file_path, report=report)

@app.route('/generate_report', methods=['POST'])
def generate_report():
    # Assuming you have some logic here to generate the report
    # For example, extracting data from the form submission
    # and creating the result.html file.

    # Sample logic to generate result.html (modify as per your logic)
    report_content = "This is a sample report content."  # Replace with actual report content
    html_file_path = "C:/path/to/your/result.html"  # Adjust the path as needed

    # Create the HTML report (replace this with your actual report generation logic)
    with open(html_file_path, 'w', encoding='utf-8') as file:
        file.write(f"<html><body><h1>Report</h1><p id='report'>{report_content}</p></body></html>")

    # Call the function to read the report out loud
    read_out_report_from_html(html_file_path)

    # Return the HTML report to the user (or redirect to another page)
    return render_template('result.html', report=report_content)  # Update this as needed

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory('uploads', filename)

if __name__ == '__main__':
    app.run(debug=True)