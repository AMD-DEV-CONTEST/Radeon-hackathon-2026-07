import json
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from database import save_career_session, get_career_sessions
from ai_service import (
    identify_career_skills,
    generate_career_questions,
    analyze_career_gaps,
    generate_career_recommendations,
    grade_career_answer
)
from code_runner import run_python_code

career_bp = Blueprint('career', __name__)


@career_bp.route('/api/career/identify-skills', methods=['POST'])
@jwt_required()
def identify_skills():
    data = request.get_json()
    career_goal = data.get('career_goal', '').strip()

    if not career_goal:
        return jsonify({'error': 'Career goal is required'}), 400

    try:
        result = identify_career_skills(career_goal)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': f'Failed to identify skills: {str(e)}'}), 500


@career_bp.route('/api/career/get-questions', methods=['POST'])
@jwt_required()
def get_questions():
    data = request.get_json()
    skill = data.get('skill', '').strip()
    career_goal = data.get('career_goal', '').strip()
    skill_description = data.get('skill_description', '').strip()

    if not skill or not career_goal:
        return jsonify({'error': 'Skill and career goal are required'}), 400

    try:
        questions = generate_career_questions(skill, career_goal, skill_description)
        return jsonify({
            'skill': skill,
            'questions': questions
        })
    except Exception as e:
        return jsonify({'error': f'Failed to generate questions: {str(e)}'}), 500


@career_bp.route('/api/career/run-code', methods=['POST'])
@jwt_required()
def execute_code():
    data = request.get_json()
    code = data.get('code', '')
    stdin_input = data.get('stdin', '')

    if not code.strip():
        return jsonify({'error': 'No code provided'}), 400

    result = run_python_code(code, stdin_input)
    return jsonify(result)


@career_bp.route('/api/career/submit-assessment', methods=['POST'])
@jwt_required()
def submit_assessment():
    user_id = int(get_jwt_identity())
    data = request.get_json()

    career_goal = data.get('career_goal', '').strip()
    required_skills = data.get('required_skills', [])
    all_answers = data.get('answers', {})  # {skill: {theory_1: "...", coding_1: "..."}}
    all_questions = data.get('questions', {})  # {skill: {theory_questions: [], coding_questions: []}}

    if not career_goal:
        return jsonify({'error': 'Career goal is required'}), 400

    skill_scores = {}
    skill_theory_scores = {}
    skill_coding_scores = {}
    questions_data = []

    for skill, qs in all_questions.items():
        theory_qs = qs.get('theory_questions', [])
        coding_qs = qs.get('coding_questions', [])
        skill_answers = all_answers.get(skill, {})

        theory_total = 0
        coding_total = 0

        # Grade theory
        for q in theory_qs:
            q_id = str(q.get('id'))
            student_ans = skill_answers.get(f"theory_{q_id}", "")
            grade = grade_career_answer(
                skill,
                q.get('question', ''),
                q.get('expected_answer', ''),
                student_ans,
                q.get('key_points', [])
            )
            score = grade.get('score', 0)
            theory_total += score
            questions_data.append({
                'skill': skill,
                'type': 'theory',
                'question': q.get('question', ''),
                'student_answer': student_ans,
                'score': round(score * 100, 1),
                'feedback': grade.get('feedback', '')
            })

        # Grade coding
        for q in coding_qs:
            q_id = str(q.get('id'))
            student_code = skill_answers.get(f"coding_{q_id}", "")

            if student_code.strip():
                run_result = run_python_code(student_code)
                expected_output = q.get('expected_output', '')
                stdout = run_result.get('stdout', '').strip()

                # Simple scoring: code runs + partial output match
                runs = run_result.get('success', False)
                if runs and expected_output:
                    output_match = expected_output.strip().lower() in stdout.lower() if expected_output else False
                    score = 1.0 if output_match else (0.6 if runs else 0.0)
                elif runs:
                    score = 0.7  # Runs but no expected output to compare
                else:
                    score = 0.0

                questions_data.append({
                    'skill': skill,
                    'type': 'coding',
                    'question': q.get('question', ''),
                    'student_code': student_code,
                    'stdout': run_result.get('stdout', ''),
                    'stderr': run_result.get('stderr', ''),
                    'score': round(score * 100, 1),
                    'runs_successfully': runs
                })
                coding_total += score
            else:
                questions_data.append({
                    'skill': skill,
                    'type': 'coding',
                    'question': q.get('question', ''),
                    'student_code': '',
                    'score': 0,
                    'runs_successfully': False
                })

        th_score = (theory_total / max(len(theory_qs), 1)) * 100 if theory_qs else 0
        cd_score = (coding_total / max(len(coding_qs), 1)) * 100 if coding_qs else 0

        # Combined skill score
        if theory_qs and coding_qs:
            combined = th_score * 0.5 + cd_score * 0.5
        elif theory_qs:
            combined = th_score
        else:
            combined = cd_score

        skill_scores[skill] = round(combined, 1)
        skill_theory_scores[skill] = round(th_score, 1)
        skill_coding_scores[skill] = round(cd_score, 1)

    # AI gap analysis
    gap_analysis = analyze_career_gaps(career_goal, skill_scores)
    overall_readiness = gap_analysis.get('overall_readiness', 0)
    roadmap = gap_analysis.get('roadmap', [])
    recommendations = generate_career_recommendations(career_goal, gap_analysis, skill_scores)

    # Overall theory and coding scores
    all_theory = [v for v in skill_theory_scores.values()]
    all_coding = [v for v in skill_coding_scores.values()]
    overall_theory = sum(all_theory) / max(len(all_theory), 1)
    overall_coding = sum(all_coding) / max(len(all_coding), 1)

    # Save session
    session_id = save_career_session(
        user_id=user_id,
        career_goal=career_goal,
        required_skills=required_skills,
        skill_scores=skill_scores,
        overall_readiness=overall_readiness,
        gap_analysis=gap_analysis,
        roadmap=roadmap,
        recommendations=recommendations,
        theory_score=overall_theory,
        coding_score=overall_coding,
        questions_data=questions_data
    )

    return jsonify({
        'session_id': session_id,
        'career_goal': career_goal,
        'skill_scores': skill_scores,
        'skill_theory_scores': skill_theory_scores,
        'skill_coding_scores': skill_coding_scores,
        'overall_readiness': round(overall_readiness, 1),
        'theory_score': round(overall_theory, 1),
        'coding_score': round(overall_coding, 1),
        'gap_analysis': gap_analysis,
        'roadmap': roadmap,
        'recommendations': recommendations,
        'questions_data': questions_data
    })


@career_bp.route('/api/career/sessions', methods=['GET'])
@jwt_required()
def get_sessions():
    user_id = int(get_jwt_identity())
    sessions = get_career_sessions(user_id)
    return jsonify({'sessions': sessions})


@career_bp.route('/api/career/report', methods=['GET'])
@jwt_required()
def get_report():
    user_id = int(get_jwt_identity())
    sessions = get_career_sessions(user_id)

    if not sessions:
        return jsonify({'report': [], 'total_sessions': 0, 'recent_sessions': []})

    # Latest session per career goal
    career_map = {}
    for s in sessions:
        goal = s['career_goal']
        if goal not in career_map:
            career_map[goal] = s

    report = []
    for goal, session in career_map.items():
        gap = session.get('gap_analysis', {})
        report.append({
            'career_goal': goal,
            'overall_readiness': session.get('overall_readiness', 0),
            'skill_scores': session.get('skill_scores', {}),
            'strong_skills': gap.get('strong_skills', []),
            'moderate_skills': gap.get('moderate_skills', []),
            'weak_skills': gap.get('weak_skills', []),
            'theory_score': session.get('theory_score', 0),
            'coding_score': session.get('coding_score', 0),
            'last_assessed': session.get('created_at')
        })

    return jsonify({
        'report': report,
        'total_sessions': len(sessions),
        'recent_sessions': sessions[:5]
    })
