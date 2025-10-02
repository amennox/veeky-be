import os
import sys
import django

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
django.setup()

# Import necessary models after Django setup
from rest_framework.authtoken.models import Token
from django.contrib.auth import get_user_model

def generate_token_for_admin():
    """
    Generate or retrieve an authentication token for the admin user.
    If the user doesn't exist or there's an error, print appropriate message.
    """
    try:
        # Get the User model and retrieve admin user
        User = get_user_model()
        user = User.objects.get(username='admin')
        
        # Create token if it doesn't exist, or get existing one
        token, created = Token.objects.get_or_create(user=user)
        
        if created:
            print("New token generated for admin user")
        else:
            print("Retrieved existing token for admin user")
            
        print(f"Token: {token.key}")
        
    except User.DoesNotExist:
        print("Error: Admin user does not exist. Please create an admin user first.")
    except Exception as e:
        print(f"An error occurred: {str(e)}")

if __name__ == "__main__":
    generate_token_for_admin()