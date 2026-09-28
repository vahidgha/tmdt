import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    # debug فقط با FLASK_DEBUG=1 روشن می‌شود — در production خاموش بماند.
    debug = os.environ.get("FLASK_DEBUG", "0").lower() in ("1", "true", "yes")
    port  = int(os.environ.get("PORT", 5050))
    app.run(debug=debug, host="0.0.0.0", port=port)
