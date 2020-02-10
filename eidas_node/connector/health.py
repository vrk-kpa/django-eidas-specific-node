from django.http import HttpResponse

def status_view(request):
    html = "<html><body>OK</body></html>"
    return HttpResponse(html)
