from django.utils import translation

class UserLanguageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and hasattr(request.user, "language"):
            translation.activate(request.user.language)
            request.LANGUAGE_CODE = request.user.language
        response = self.get_response(request)
        translation.deactivate()
        return response