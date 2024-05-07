import socket

def communicate(host, port, request):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((host, port))
    s.send(request.encode('utf-8'))
    response = s.recv(1024).decode('utf-8')
    s.close()
    return response
