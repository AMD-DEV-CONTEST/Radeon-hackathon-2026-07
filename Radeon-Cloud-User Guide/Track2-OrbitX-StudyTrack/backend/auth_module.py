import re
import sqlite3

import bcrypt
from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from database import (
    create_user,
    get_user_by_email,
    get_user_by_id,
    update_user_password_hash,
)

auth_bp = Blueprint('auth', __name__)

EMAIL_PATTERN = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(password, stored_hash):
    try:
        if stored_hash.startswith('$2'):
            return bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))
        return password == stored_hash
    except (ValueError, TypeError):
        return False


def user_response(user):
    return {
        'id': int(user['id']),
        'username': str(user['username']),
        'email': str(user['email']),
    }


@auth_bp.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}
    username = data.get('username', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    confirm_password = data.get('confirm_password', data.get('confirm', ''))

    if not username:
        return jsonify({'error': 'Username is required'}), 400
    if not email:
        return jsonify({'error': 'Email is required'}), 400
    if not password:
        return jsonify({'error': 'Password is required'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    if not EMAIL_PATTERN.match(email):
        return jsonify({'error': 'Enter a valid email address'}), 400
    if confirm_password and password != confirm_password:
        return jsonify({'error': 'Passwords do not match'}), 400

    if get_user_by_email(email):
        return jsonify({'error': 'Email already exists. Please use a different email address.'}), 409

    password_hash = hash_password(password)

    try:
        user = create_user(username, email, password_hash)
        access_token = create_access_token(identity=str(user['id']))
        return jsonify({'access_token': access_token, 'user': user_response(user)}), 201
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Username already exists. Please choose another username.'}), 409
    except Exception as e:
        return jsonify({'error': 'Registration failed. Please try again.'}), 500


@auth_bp.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400

    user = get_user_by_email(email)
    if not user:
        return jsonify({'error': 'Invalid Email or Password'}), 401

    if not verify_password(password, user['password_hash']):
        return jsonify({'error': 'Invalid Email or Password'}), 401

    if not user['password_hash'].startswith('$2'):
        update_user_password_hash(user['id'], hash_password(password))

    access_token = create_access_token(identity=str(user['id']))
    return jsonify({'access_token': access_token, 'user': user_response(user)})


@auth_bp.route('/api/auth/me', methods=['GET'])
@jwt_required()
def get_me():
    try:
        user_id = int(get_jwt_identity())
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid authentication token'}), 401

    user = get_user_by_id(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify(user_response(user))
