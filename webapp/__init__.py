# webapp/__init__.py

from flask import Flask
import os

def create_app(config_object="core.config"):
    app = Flask(__name__, instance_relative_config=False)
    # Load shared settings
    app.config.from_object(config_object)

    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret–change-me")

    # Example: register a simple blueprint
    from webapp.routes import bp
    app.register_blueprint(bp)

    return app
