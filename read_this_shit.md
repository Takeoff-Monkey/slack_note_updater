🚀 Slack Note-Logger Bot — 60-Second Test Guide
What you do	What the bot does
1. Start a thread Type a message that contains a job number in the form #12345! (hash, five digits, exclamation).	Grabs that job number, finds the matching Google Doc, and replies “Got it!”
2. Add notes Keep replying in the same thread.	Every reply (who, time, text) is appended to the bottom of the Google Doc.
3. Drop images or files Attach images or paste links in the thread.	Images are pushed to the doc via our GAS script; file links are inserted as clickable attachments.
Tips for Testers
•	Make sure the job number is exactly #12345! (no spaces).
•	You can add multiple images in one reply.
•	If the bot fails, it will respond with a warning emoji; grab a screenshot and DM Tommy.


Known Limits (for now)
•	Only works in channels where the bot has been invited.
•	PDFs / non-image files are stored as links, not inline.
•	Thread must start with the job number — edits don’t count.

![image](https://github.com/user-attachments/assets/ff47fef8-84cf-4ef7-b885-f6e267752bcd)


