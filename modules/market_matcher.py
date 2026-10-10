def get_local_job_catalog() -> list:
  """Curated catalog of entry-level tech roles in the local market."""
  return [
      {
          "id": "job_01",
          "title": "Junior Android / Mobile Developer",
          "company": "TechLogix / Systems Ltd",
          "location": "Islamabad / Rawalpindi (Hybrid)",
          "required_skills": [
              "Java",
              "Kotlin",
              "Android SDK",
              "Jetpack Compose",
              "REST APIs",
              "Git",
          ],
          "description": (
              "Build modern Android interfaces, handle API integrations, and"
              " optimize native mobile application performance."
          ),
      },
      {
          "id": "job_02",
          "title": "Associate Python Backend Engineer",
          "company": "Emumba / Arbisoft",
          "location": "Islamabad / Lahore",
          "required_skills": [
              "Python",
              "FastAPI",
              "PostgreSQL",
              "REST APIs",
              "Docker",
              "Git",
          ],
          "description": (
              "Develop scalable backend services, design relational database"
              " schemas, and integrate microservice APIs."
          ),
      },
      {
          "id": "job_03",
          "title": "AI & Data Solutions Intern",
          "company": "National Incubation Center Partner",
          "location": "Islamabad",
          "required_skills": [
              "Python",
              "Pandas",
              "Machine Learning Basics",
              "LangChain",
              "Data Preprocessing",
          ],
          "description": (
              "Assist in creating AI prototypes, parsing datasets, and"
              " integrating LLM workflow automation."
          ),
      },
  ]


def calculate_match(student_skills: list, job_skills: list) -> dict:
  """Calculates matching skills, gaps, and an ATS fit percentage."""
  student_set = {s.lower().strip() for s in student_skills}

  matched = [req for req in job_skills if req.lower().strip() in student_set]
  missing = [
      req for req in job_skills if req.lower().strip() not in student_set
  ]

  score = int((len(matched) / len(job_skills)) * 100) if job_skills else 0

  return {
      "match_score": score,
      "matched_skills": matched,
      "missing_skills": missing,
  }