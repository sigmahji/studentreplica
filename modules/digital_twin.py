import json
from pypdf import PdfReader


def extract_text_from_pdf(uploaded_file) -> str:
  """Extracts raw text from an uploaded PDF file."""
  try:
    reader = PdfReader(uploaded_file)
    text = ""
    for page in reader.pages:
      extracted = page.extract_text()
      if extracted:
        text += extracted + "\n"
    return text.strip()
  except Exception as e:
    return f"Error reading PDF: {str(e)}"


def build_digital_twin_prompt(academic_text: str) -> str:
  """Builds prompt to turn extracted academic text into structured JSON."""
  return f"""
Analyze this student's academic background and return ONLY a valid JSON object.
Schema:
{{
  "name": "Student Name or Candidate",
  "degree": "Degree / Program",
  "verified_skills": ["Skill 1", "Skill 2"],
  "core_courses": ["Course 1", "Course 2"],
  "experience_level": "Beginner / Intermediate / Advanced",
  "strengths_summary": "Short 2-sentence summary of academic capability."
}}

Student Document Text:
{academic_text}
"""


def get_demo_student() -> dict:
  """Zero-latency fallback student profile for hackathon demo."""
  return {
      "name": "Muhammad Owais",
      "degree": "B.S. Software Engineering",
      "verified_skills": [
          "Python",
          "C++",
          "Java",
          "Object-Oriented Programming",
          "Data Structures & Algorithms",
          "Database Systems",
          "Android Basics",
          "Git",
      ],
      "core_courses": [
          "Data Structures",
          "OOP",
          "Digital Logic Design",
          "Database Management Systems",
          "Software Engineering Principles",
      ],
      "experience_level": "Undergraduate (Junior)",
      "strengths_summary": (
          "Strong foundation in core computing principles, algorithmic"
          " problem solving, and object-oriented application design."
      ),
  }