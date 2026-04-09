// mock-server.js
const express = require('express');
const app = express();
const port = 3000;

// Middleware to parse JSON bodies
app.use(express.json());

// Mock login endpoint
app.post('/api/login', (req, res) => {
  const { username, password } = req.body;
  
  // Mock successful login
  if (username === 'testuser' && password === 'password') {
    return res.status(200).json({ 
      success: true, 
      token: 'mock-jwt-token',
      user: { id: 1, username: 'testuser' }
    });
  }
  
  // Mock failed login
  return res.status(401).json({ 
    success: false, 
    message: 'Invalid credentials' 
  });
});

// Mock protected route
app.get('/api/protected', (req, res) => {
  const authHeader = req.headers.authorization;
  
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return res.status(401).json({ 
      success: false, 
      message: 'No token provided' 
    });
  }
  
  // In a real app, you would verify the JWT here
  return res.status(200).json({ 
    success: true, 
    data: 'Protected data' 
  });
});

// Serve a simple HTML page for the root route
app.get('/', (req, res) => {
  res.send(`
    <!DOCTYPE html>
    <html>
      <head>
        <title>Test Application</title>
      </head>
      <body>
        <h1>Welcome to the Test Application</h1>
        <div id="login-form">
          <input type="text" id="username" placeholder="Username">
          <input type="password" id="password" placeholder="Password">
          <button id="login-btn">Login</button>
        </div>
        <div id="protected-content" style="display: none;">
          <h2>Protected Content</h2>
          <p>This is only visible after login</p>
        </div>
        <script>
          document.getElementById('login-btn').addEventListener('click', async () => {
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            
            try {
              const response = await fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
              });
              
              const data = await response.json();
              
              if (data.success) {
                document.getElementById('login-form').style.display = 'none';
                document.getElementById('protected-content').style.display = 'block';
                localStorage.setItem('token', data.token);
              } else {
                alert('Login failed: ' + data.message);
              }
            } catch (error) {
              console.error('Login error:', error);
              alert('Login error: ' + error.message);
            }
          });
        </script>
      </body>
    </html>
  `);
});

// In mock-server.js, update the /boundary-test route
app.get('/boundary-test', (req, res) => {
  console.log('Serving boundary test page');
  res.send(`
    <!DOCTYPE html>
    <html>
      <head>
        <title>Boundary Test Page</title>
        <script>
          // Add a simple script to log when the page loads
          window.addEventListener('load', () => {
            console.log('Boundary test page loaded');
          });
        </script>
      </head>
      <body>
        <h1>Boundary Test Page</h1>
        <form id="boundary-form">
          <input type="text" id="boundary-input" name="boundary-input" placeholder="Enter value">
          <button type="submit">Submit</button>
        </form>
        <div id="result"></div>
      </body>
    </html>
  `);
});


app.listen(port, () => {
  console.log(`Mock server running at http://localhost:${port}`);
});