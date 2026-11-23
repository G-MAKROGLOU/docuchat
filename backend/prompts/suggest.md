Suggest follow-up questions the user can click after the last answer. Return only JSON: {"suggestions": ["...", "..."]} with at most 3 questions.

Rules:
- Each question can be answered from a drug label: dosage, side effects, warnings, interactions, use in pregnancy, and so on.
- Name the medicine in each question, so the question stands alone.
- Do not repeat what the last answer already covers.
- Keep each question under 80 characters.
- Return {"suggestions": []} when no follow-up fits.
