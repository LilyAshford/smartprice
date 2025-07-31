''' The serve.py file with the waitress server was our diagnostic tool.
    However, if in the distant future we will have to run this application on a Windows server,
    then waitress is one of the recommended ways.
    So we left the file as a keepsake, it does not interfere.'''


from app import create_app
from waitress import serve
import os
from dotenv import load_dotenv

load_dotenv()

try:
    config_name = os.getenv('FLASK_CONFIG') or 'development'
    print(f"Using configuration: {config_name}")
    print(f"Database URL: {os.getenv('DATABASE_URL')}")

    app = create_app(config_name)

    if __name__ == '__main__':
        print("Starting server with waitress...")
        serve(app, host='0.0.0.0', port=5000)
except Exception as e:
    print(f"Failed to start server: {str(e)}")
    raise