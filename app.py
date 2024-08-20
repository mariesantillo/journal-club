from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import firebase_admin
from firebase_admin import credentials, auth, firestore
import os

app = Flask(__name__)
app.config.from_object(Config)

# Initialize Firebase
cred = credentials.Certificate("/Users/mariefrancine/Desktop/JC/journalclub-6a9bb-firebase-adminsdk-vqslj-34a110ae0f.json")
firebase_admin.initialize_app(cred, {
    'storageBucket': 'journalclub-6a9bb.appspot.com'
})
db = firestore.client()
bucket = storage.bucket()

@app.route('/home')
def home(): 
    articles_ref = db.collection('articles')
    articles = [doc.to_dict() for doc in articles_ref.stream()]
    return render_template('home.html', articles=articles)

@app.route('/vote/<string:article_id>', methods=['POST'])
def vote(article_id):
    user_id = request.form['user_id']  # Assuming you get the user ID from the session or form
    vote_ref = db.collection('votes').document(f'{user_id}_{article_id}')

    # Check if the user has already voted
    if vote_ref.get().exists:
        flash('You have already voted for this article!', 'warning')
    else:
        # Record the vote in Firestore
        vote_ref.set({
            'user_id': user_id,
            'article_id': article_id,
            'voted_at': datetime.datetime.now()
        })
        flash('Voted successfully!', 'success')
    
    return redirect(url_for('home'))

@app.route('/results')
def results():
    articles_ref = db.collection('articles')
    articles = [doc.to_dict() for doc in articles_ref.stream()]

    results = []
    for article in articles:
        votes_ref = db.collection('votes').where('article_id', '==', article['id'])
        vote_count = len([v for v in votes_ref.stream()])
        results.append({
            'title': article['title'],
            'vote_count': vote_count
        })

    return render_template('results.html', results=results)

@app.route('/secure-page')
def secure_page():
    id_token = request.headers.get('Authorization').split(' ').pop()
    try: 
        decoded_token = auth.verify_id_token(id_token)
        uid = decoded_token['uid']
        return render_template('secure_page.html')
    except Exception as e:
        return jsonify({'message': 'Unauthorized'}), 401

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    token = data['idToken']
    
    try:
        decoded_token = auth.verify_id_token(token)
        uid = decoded_token['uid']
        return jsonify({"message": "Login successful"}), 200
    except:
        return jsonify({"error": "Invalid token"}), 401

if __name__ == '__main__':
    app.run(debug=True)

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST':
        title = request.form['title']
        file = request.files['file']
        
        if file and title:
            # Save the file to Firebase Storage
            blob = bucket.blob(file.filename)
            blob.upload_from_file(file, content_type=file.content_type)
            file_url = blob.public_url
            
            # Save metadata to Firestore
            article_ref = db.collection('articles').add({
                'title': title,
                'filename': file.filename,
                'file_url': file_url,
                'uploaded_at': datetime.datetime.now()
            })
            flash('Article uploaded successfully!', 'success')
            return redirect(url_for('home'))
    
    return render_template('upload.html')
