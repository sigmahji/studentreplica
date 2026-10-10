def generate_tailored_cv_prompt(student_profile: dict, job_data: dict, match_data: dict) -> str:
    """Creates a prompt to synthesize an ATS-optimized CV in Markdown."""
    return f"""
You are an expert technical career coach and ATS resume writer.
Create a high-impact, ATS-friendly CV in clean Markdown format for this student applying for the target job.

STUDENT PROFILE:
- Name: {student_profile.get('name')}
- Degree: {student_profile.get('degree')}
- Verified Skills: {', '.join(student_profile.get('verified_skills', []))}
- Key Courses: {', '.join(student_profile.get('core_courses', []))}

TARGET JOB:
- Title: {job_data.get('title')} at {job_data.get('company')}
- Required Skills: {', '.join(job_data.get('required_skills', []))}
- Matched Skills: {', '.join(match_data.get('matched_skills', []))}
- Skills in Progress: {', '.join(match_data.get('missing_skills', []))}

INSTRUCTIONS:
1. Write a 3-sentence target objective aligned with the job.
2. Structure sections: Education, Technical Skills (prioritize matching keywords), Core Coursework, Selected Projects, and Certifications.
3. Use Google's X-Y-Z formula for bullet points: "Accomplished [X] measured by [Y], by doing [Z]".
4. Return ONLY the Markdown text.
"""

def generate_interview_prep_prompt(job_title: str, missing_skills: list) -> str:
    """Generates rapid mock interview questions for identified skill gaps."""
    skills_str = ", ".join(missing_skills) if missing_skills else "Core skills"
    return f"""
Act as a senior technical interviewer for a {job_title} role.
Generate:
1. Exactly 3 technical questions specifically targeting these skill gap areas: {skills_str}.
2. Exactly 2 behavioral situational questions.
3. Provide a brief 1-line 'What the interviewer looks for' guide under each question.
Keep it concise and clear.
"""