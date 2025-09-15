@app.route('/')
def dashboard():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Access Control System</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; }
            .container { max-width: 800px; margin: 0 auto; }
            .card { background: #f5f5f5; padding: 20px; margin: 20px 0; border-radius: 8px; }
            h1 { color: #2c3e50; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Access Control System</h1>
            <div class="card">
                <h2>System Status</h2>
                <p>✅ Flask application running successfully</p>
                <p>✅ Database initialized</p>
                <p>✅ API endpoints active</p>
            </div>
            <div class="card">
                <h2>Test Endpoints</h2>
                <p><strong>Webhook URLs:</strong></p>
                <ul>
                    <li>Card Scan: POST /webhook/card_scanned</li>
                    <li>PIN Entry: POST /webhook/pin_entered</li>
                </ul>
            </div>
            <div class="card">
                <h2>API Endpoints</h2>
                <ul>
                    <li>GET /api/users - List users</li>
                    <li>POST /api/users - Create user</li>
                </ul>
            </div>
        </div>
    </body>
    </html>
    '''
