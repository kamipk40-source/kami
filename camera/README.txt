HAZRI HISAB CAMERA PROGRAM  (Windows 10)
=========================================
What it does: a camera at the office gate sees a face, finds the person, and sends
"this person arrived at this time" to the Hazri Hisab app. Only the FIRST sighting of
each person each day is kept. The app then marks Present or Late using your Rules.

Do this once, in order
----------------------
1. Install Python 3.11 from https://www.python.org/downloads/ . On the first screen
   tick "Add python.exe to PATH".
2. Double-click  setup_windows.bat  (needs internet; takes a few minutes).
3. Copy  config.example.ini  to  config.ini  and open it in Notepad:
   - email / password: the CAMERA user you made in Supabase (not your admin login)
   - [cameras]: your camera address (see the examples inside). Use  0  for a USB webcam.
4. Double-click  check_camera.bat . It must say: Models OK, Database sign-in OK,
   Camera OK. It saves a snapshot_*.jpg picture so you can see what the camera sees.
5. Put employees.csv in this folder. Run in a Command Prompt here:
        python hr_camera.py folders
   This makes one folder per person inside  faces\ . Put 3 to 5 clear photos of that
   person in their folder (front face, good light, no sunglasses, a smile and a neutral face).
6. Double-click  enroll.bat . It tells you who has no usable photo.
7. Test:   python hr_camera.py run --show     (a window shows green/red boxes; press q to quit)
8. Daily use: double-click  run_camera.bat  and leave the window open.
   To start by itself when the PC turns on: press Win+R, type  shell:startup , and put
   a shortcut to run_camera.bat in that folder. The PC must stay on during office hours.

Camera position
---------------
At the gate, at face height, 1 to 2 metres away, with light on the face (not behind the person).
A ceiling dome camera looking down does not work well. Use the main stream (best picture).

Things to know
--------------
* A photo held up to the camera can fool it. This program has no "live person" check.
  Keep the camera where a guard or staff can see it.
* If the program was off in the morning, a person is recorded at the time they are first
  seen after it starts. Fix such days by hand in the app (Attendance tab).
* Twins or very similar faces can be mixed up. Raise  threshold  in config.ini if that happens.
* People who work from home are never seen by the camera. Mark them by hand in the app.
* Face data is sensitive personal data. Get written permission from staff, keep the faces\
  folder and faces.pkl private (the program stores only numbers, but keep the photos safe),
  and never upload them to GitHub.
* If a name is wrong, delete that person's photos, add better ones, and run enroll again.
