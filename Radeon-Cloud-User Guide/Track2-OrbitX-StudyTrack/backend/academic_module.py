import json
import io
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from database import save_academic_session, get_academic_sessions
from ai_service import (
    generate_academic_quiz,
    analyze_academic_mistakes,
    grade_theory_answer,
    grade_short_answer,
    generate_study_recommendations
)

academic_bp = Blueprint('academic', __name__)

def extract_pdf_text(file_bytes: bytes) -> str:
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text()
        return text[:5000]
    except Exception:
        return ""


@academic_bp.route('/api/academic/generate-quiz', methods=['POST'])
@jwt_required()
def generate_quiz():
    subject = request.form.get('subject', '').strip()
    topic = request.form.get('topic', '').strip()
    text_content = request.form.get('content', '').strip()

    if not subject or not topic:
        return jsonify({'error': 'Subject and topic are required'}), 400

    # Handle file upload
    content = text_content
    if 'file' in request.files:
        file = request.files['file']
        if file.filename:
            file_bytes = file.read()
            if file.filename.lower().endswith('.pdf'):
                extracted = extract_pdf_text(file_bytes)
                content = extracted or text_content
            else:
                # Plain text file
                content = file_bytes.decode('utf-8', errors='ignore')[:5000]

    try:
        quiz_data = generate_academic_quiz(subject, topic, content)
        return jsonify({
            'subject': subject,
            'topic': topic,
            'quiz': quiz_data
        })
    except Exception as e:
        return jsonify({'error': f'Failed to generate quiz: {str(e)}'}), 500


@academic_bp.route('/api/academic/submit-quiz', methods=['POST'])
@jwt_required()
def submit_quiz():
    user_id = int(get_jwt_identity())
    data = request.get_json()

    subject = data.get('subject', '').strip()
    topic = data.get('topic', '').strip()
    quiz = data.get('quiz', {})
    answers = data.get('answers', {})

    if not subject or not topic or not quiz:
        return jsonify({'error': 'Subject, topic, and quiz data are required'}), 400

    mcqs = quiz.get('mcqs', [])
    theory_qs = quiz.get('theory_questions', [])
    short_qs = quiz.get('short_answer_questions', [])

    mcq_results = []
    wrong_questions = []

    # Grade MCQs
    mcq_correct = 0
    for q in mcqs:
        q_id = str(q.get('id'))
        student_ans = answers.get(f"mcq_{q_id}", "")
        is_correct = student_ans.strip() == q.get('correct_answer', '').strip()
        if is_correct:
            mcq_correct += 1
        else:
            wrong_questions.append({
                'question': q.get('question'),
                'concept': q.get('concept', topic),
                'student_answer': student_ans,
                'correct_answer': q.get('correct_answer')
            })
        mcq_results.append({
            'id': q_id,
            'question': q.get('question'),
            'student_answer': student_ans,
            'correct_answer': q.get('correct_answer'),
            'is_correct': is_correct,
            'explanation': q.get('explanation', ''),
            'concept': q.get('concept', '')
        })

    mcq_score = (mcq_correct / max(len(mcqs), 1)) * 100

    # Grade theory questions
    theory_results = []
    theory_total = 0
    for q in theory_qs:
        q_id = str(q.get('id'))
        student_ans = answers.get(f"theory_{q_id}", "")
        grade = grade_theory_answer(
            q.get('question'),
            q.get('expected_answer', ''),
            student_ans,
            q.get('key_points', [])
        )
        score_pct = grade.get('score', 0) * 100
        theory_total += grade.get('score', 0)
        if score_pct < 60:
            wrong_questions.append({
                'question': q.get('question'),
                'concept': q.get('concept', topic),
                'student_answer': student_ans,
                'correct_answer': q.get('expected_answer', '')
            })
        theory_results.append({
            'id': q_id,
            'question': q.get('question'),
            'student_answer': student_ans,
            'score': score_pct,
            'feedback': grade.get('feedback', ''),
            'covered_points': grade.get('covered_points', []),
            'missed_points': grade.get('missed_points', []),
            'concept': q.get('concept', '')
        })

    theory_score = (theory_total / max(len(theory_qs), 1)) * 100

    # Grade short answer questions
    short_results = []
    short_total = 0
    for q in short_qs:
        q_id = str(q.get('id'))
        student_ans = answers.get(f"short_{q_id}", "")
        grade = grade_short_answer(
            q.get('question'),
            q.get('expected_answer', ''),
            student_ans,
            q.get('keywords', [])
        )
        score_pct = grade.get('score', 0) * 100
        short_total += grade.get('score', 0)
        if score_pct < 60:
            wrong_questions.append({
                'question': q.get('question'),
                'concept': q.get('concept', topic),
                'student_answer': student_ans,
                'correct_answer': q.get('expected_answer', '')
            })
        short_results.append({
            'id': q_id,
            'question': q.get('question'),
            'student_answer': student_ans,
            'score': score_pct,
            'feedback': grade.get('feedback', ''),
            'concept': q.get('concept', '')
        })

    short_score = (short_total / max(len(short_qs), 1)) * 100

    # Overall score (weighted: MCQ 40%, Theory 40%, Short 20%)
    total_score = (mcq_score * 0.4) + (theory_score * 0.4) + (short_score * 0.2)

    # AI mistake analysis
    mistake_analysis = analyze_academic_mistakes(subject, topic, wrong_questions)
    weak_areas = mistake_analysis.get('weak_concepts', [])
    ai_analysis = mistake_analysis.get('analysis', '')

    # Generate personalized recommendations
    recommendations = generate_study_recommendations(subject, topic, weak_areas, total_score)

    # Build questions data for storage
    questions_data = {
        'mcq_results': mcq_results,
        'theory_results': theory_results,
        'short_results': short_results
    }

    # Save to database
    session_id = save_academic_session(
        user_id=user_id,
        subject=subject,
        topic=topic,
        total_questions=len(mcqs) + len(theory_qs) + len(short_qs),
        score=total_score,
        mcq_score=mcq_score,
        theory_score=theory_score,
        short_score=short_score,
        weak_areas=weak_areas,
        ai_analysis=ai_analysis,
        recommendations=recommendations,
        questions_data=questions_data
    )

    return jsonify({
        'session_id': session_id,
        'subject': subject,
        'topic': topic,
        'scores': {
            'overall': round(total_score, 1),
            'mcq': round(mcq_score, 1),
            'theory': round(theory_score, 1),
            'short_answer': round(short_score, 1)
        },
        'mcq_results': mcq_results,
        'theory_results': theory_results,
        'short_results': short_results,
        'weak_areas': weak_areas,
        'specific_gaps': mistake_analysis.get('specific_gaps', {}),
        'ai_analysis': ai_analysis,
        'recommendations': recommendations,
        'total_correct': mcq_correct,
        'total_mcqs': len(mcqs)
    })


@academic_bp.route('/api/academic/sessions', methods=['GET'])
@jwt_required()
def get_sessions():
    user_id = int(get_jwt_identity())
    sessions = get_academic_sessions(user_id)
    return jsonify({'sessions': sessions})


@academic_bp.route('/api/academic/report', methods=['GET'])
@jwt_required()
def get_report():
    user_id = int(get_jwt_identity())
    sessions = get_academic_sessions(user_id)

    # Aggregate by subject → topic
    subject_map = {}
    for s in sessions:
        subj = s['subject']
        if subj not in subject_map:
            subject_map[subj] = {'topics': {}, 'scores': []}
        topic = s['topic']
        if topic not in subject_map[subj]['topics']:
            subject_map[subj]['topics'][topic] = {'scores': [], 'weak_areas': []}
        subject_map[subj]['topics'][topic]['scores'].append(s['score'])
        subject_map[subj]['topics'][topic]['weak_areas'].extend(s.get('weak_areas', []))
        subject_map[subj]['scores'].append(s['score'])

    # Build report
    report = []
    for subj, data in subject_map.items():
        avg_score = sum(data['scores']) / len(data['scores'])
        topics = []
        for topic, tdata in data['topics'].items():
            tavg = sum(tdata['scores']) / len(tdata['scores'])
            status = 'strong' if tavg >= 75 else ('moderate' if tavg >= 50 else 'weak')
            topics.append({
                'topic': topic,
                'avg_score': round(tavg, 1),
                'attempts': len(tdata['scores']),
                'status': status,
                'weak_areas': list(set(tdata['weak_areas']))
            })
        report.append({
            'subject': subj,
            'avg_score': round(avg_score, 1),
            'topic_count': len(topics),
            'topics': topics
        })

    return jsonify({
        'report': report,
        'total_sessions': len(sessions),
        'recent_sessions': sessions[:5]
    })
