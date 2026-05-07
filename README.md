This tool is an automated job application bot built with Python and Playwright that helps users apply to jobs faster by auto-filling application forms, uploading resumes, and navigating common ATS systems like LinkedIn, Greenhouse, Lever, and Workday. It uses a configurable profile section where users store personal details (name, email, LinkedIn, resume path, work authorization, etc.), then automatically maps those details into application fields it detects on webpages. The script is designed conservatively with a “review mode” that pauses before submission so users can verify everything manually, reducing accidental or incorrect applications. Important limitations are that many job sites use CAPTCHAs, anti-bot protections, custom widgets, or dynamic questions, so some applications still require human review and custom adjustments.

1. Update the CONFIG section with your name, email, phone, LinkedIn, resume path, and job links.
2. Install Python 3.10+ and Playwright.
3. Log in to LinkedIn or the job site manually once.
4. Run the script with python job_apply_bot.py.
5. The bot opens each job link, clicks Apply, fills matching fields, and uploads your resume.
6. In review mode, it pauses so you can check everything and submit manually.

