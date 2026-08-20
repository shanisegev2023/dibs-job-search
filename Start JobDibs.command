#!/bin/bash
# הפעלה בלחיצה כפולה (macOS). אם נפתחת שגיאה על פייתון,
# אשרי את ההתקנה שמק מציע — זו התקנה חד-פעמית.
cd "$(dirname "$0")" || exit 1
echo ""
echo "  מפעילה את JobDibs…"
echo "  לעצירה: סגרי את החלון הזה או לחצי Ctrl+C"
echo ""
python3 app.py || {
  echo ""
  echo "  לא נמצא python3. התקיני מ- https://www.python.org/downloads/"
  echo ""
  read -r -p "  הקישי Enter לסגירה " _
}
