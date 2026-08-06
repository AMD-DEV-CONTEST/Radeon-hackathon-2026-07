import os
from flask import Flask
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from dotenv import load_dotenv

load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

app = Flask(__name__)

jwt_secret_key = os.getenv('JWT_SECRET_KEY')
if not jwt_secret_key:
    raise RuntimeError('JWT_SECRET_KEY environment variable is required')

app.config['JWT_SECRET_KEY'] = jwt_secret_key
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = int(os.getenv('JWT_ACCESS_TOKEN_EXPIRES', str(3600 * 24 * 7)))
JWTManager(app)

from database import init_db
from auth_module import auth_bp
from academic_module import academic_bp
from career_module import career_bp

cors_origins = [
    origin.strip()
    for origin in os.getenv('FRONTEND_URL', '').split(',')
    if origin.strip()
]

if cors_origins:
    CORS(
        app,
        origins=cors_origins,
        allow_headers=['Content-Type', 'Authorization'],
        methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
        expose_headers=['Content-Type'],
        supports_credentials=True,
    )

init_db()

app.register_blueprint(auth_bp)
app.register_blueprint(academic_bp)
app.register_blueprint(career_bp)


@app.route('/', methods=['GET'])
def index():
    return {
        'status': 'ok',
        'app': 'StudyTrack API',
        'message': 'Backend is running. Use /api/health.',
        'endpoints': {
            'health': '/api/health',
            'login': '/api/auth/login',
            'register': '/api/auth/register',
            'me': '/api/auth/me',
        },
    }


@app.route('/api', methods=['GET'])
def api_index():
    return {
        'status': 'ok',
        'message': 'StudyTrack API is running.',
        'health': '/api/health',
    }


@app.route('/api/health', methods=['GET'])
def health():
    return {'status': 'ok', 'app': 'StudyTrack API', 'version': '1.0.0'}

import os

@app.route("/api/debug-env", methods=["GET"])
def debug_env():
    return {
        "groq_exists": bool(os.getenv("GROQ_API_KEY")),
        "gemini_exists": bool(os.getenv("GEMINI_API_KEY")),
        "jwt_exists": bool(os.getenv("JWT_SECRET_KEY"))
    }, 200