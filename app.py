from flask import Flask, render_template, request, redirect, session, flash, url_for
from flask_socketio import SocketIO, emit
from geopy.distance import geodesic
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app)

# ---------------- Database Connection ----------------
db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="132003",
    database="camp_ride"
)

# ---------------- In-Memory Storage ----------------
driver_locations = {}
students = []




# ---------------- LOGIN ----------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        name = request.form['name']
        password = request.form['password']

        # ✅ Hardcoded Admin Check
        if name.lower() == "admin" and password == "admin123":
            session['user_name'] = "Admin"
            session['is_admin'] = True
            session['role'] = "admin"
            flash("Welcome Admin!")
            return redirect(url_for('admin_panel'))

        # ✅ Normal user login from DB
        cursor = db.cursor(dictionary=True, buffered=True)
        cursor.execute("SELECT * FROM users WHERE name=%s", (name,))
        user = cursor.fetchone()
        cursor.close()

        if user is None:
            flash("User not found.")
            return redirect(url_for('login'))

        if check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            session['user_email'] = user['email']
            session['role'] = user['role']
            session['is_admin'] = (user['role'].lower() == "admin")
            flash("Login successful!")

            if user['role'].lower() == "driver":
                return redirect(url_for('driver_panel'))
            else:
                return redirect(url_for('student_panel'))
        else:
            flash("Invalid username or password.")
            return redirect(url_for('login'))

    return render_template('login.html')



# ---------------- REGISTER ----------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        role = request.form['role']
        password = generate_password_hash(request.form['password'])

        cursor = db.cursor(buffered=True)
        cursor.execute(
            "INSERT INTO users (name, email, password, role) VALUES (%s, %s, %s, %s)",
            (name, email, password, role)
        )
        db.commit()
        cursor.close()

        flash("Registration successful! Please log in.")

        if role.lower() == "driver":
            return redirect(url_for('driver_bus', user_email=email))
        else:
            return redirect(url_for('login'))

    return render_template('register.html')



# ---------------- ROUTES ----------------
# Show all users in admin panel
@app.route('/admin/users')
def manage_users():
    if 'is_admin' in session and session['is_admin']:
        cursor = db.cursor(dictionary=True, buffered=True)
        cursor.execute("SELECT id, name, email FROM users")
        users = cursor.fetchall()
        cursor.close()
        return render_template("admin_users.html", users=users, name=session['user_name'])
    else:
        flash("Unauthorized access!")
        return redirect(url_for('login'))


# Delete user by ID
@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    if 'is_admin' in session and session['is_admin']:
        cursor = db.cursor(buffered=True)
        cursor.execute("DELETE FROM users WHERE id=%s", (user_id,))
        db.commit()
        cursor.close()
        flash("User deleted successfully!")
        return redirect(url_for('manage_users'))
    else:
        flash("Unauthorized action!")
        return redirect(url_for('login'))

@app.route('/')
def home():
    return render_template('home.html')

def admin():
    if 'is_admin' in session and session['is_admin']:
        return render_template('admin_panel.html', name=session['user_name'])
    else:
        flash("Unauthorized access!")
        return redirect(url_for('login'))

@app.route('/home')
def home_page():
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))
    return render_template('home.html', name=session.get('user_name'))



@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.")
    return redirect(url_for('login'))

@app.route('/driver_bus', methods=['GET', 'POST'])
def driver_bus():
    user_email = request.args.get('user_email')

    if request.method == 'POST':
        driverName = request.form['driverName']
        driverEmail = request.form['driverEmail']
        driverPhone = request.form['driverPhone']
        driverLicense = request.form['driverLicense']
        busNumber = request.form['busNumber']
        busRoute = request.form['busRoute']

        cursor = db.cursor(buffered=True)
        cursor.execute(
            "INSERT INTO drivers (name, email, phone, license_number, bus_number, bus_route) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (driverName, driverEmail, driverPhone, driverLicense, busNumber, busRoute)
        )
        db.commit()
        cursor.close()

        flash("Driver and bus information added successfully!")

        # Store driver email in session so driver panel works
        session['user_email'] = driverEmail
        session['role'] = "driver"
        return redirect(url_for('driver_panel'))

    return render_template('driver_bus.html', driver_email=user_email)




@app.route('/student_panel')
def student_panel():
    if 'user_id' not in session:
        flash("Please log in first.")
        return redirect(url_for('login'))
    return render_template('student.html', name=session.get('user_name'))

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/manage_drivers')
def manage_drivers():
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT * FROM drivers")
    drivers = cursor.fetchall()
    cursor.close()
    return render_template('manage_drivers.html', drivers=drivers)
@app.route('/update_driver/<int:id>', methods=['POST'])
def update_driver(id):
    name = request.form['name']
    email = request.form['email']
    phone = request.form['phone']
    license_number = request.form['license_number']
    bus_number = request.form['bus_number']
    bus_route = request.form['bus_route']

    cursor = db.cursor()
    cursor.execute("""
        UPDATE drivers
        SET name=%s, email=%s, phone=%s, license_number=%s, bus_number=%s, bus_route=%s
        WHERE id=%s
    """, (name, email, phone, license_number, bus_number, bus_route, id))
    db.commit()
    cursor.close()

    flash("Driver details updated successfully!")
    return redirect(url_for('manage_drivers'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        name = request.form['name']
        password = request.form['password']

        cursor = db.cursor(dictionary=True, buffered=True)
        cursor.execute("SELECT * FROM users WHERE name=%s", (name,))
        user = cursor.fetchone()
        cursor.close()

        if not user:
            flash("User not found.")
            return redirect(url_for('login'))

        if check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            session['user_email'] = user['email']
            session['role'] = user['role']
            session['is_admin'] = (user['role'].lower() == "admin")

            flash("Login successful!")

            if user['role'].lower() == "driver":
                return redirect(url_for('driver_panel'))
            elif user['role'].lower() == "admin":
                return redirect(url_for('admin_panel'))
            else:
                return redirect(url_for('student_panel'))
        else:
            flash("Invalid username or password.")
            return redirect(url_for('login'))

    return render_template('login.html')





# ---------------- SOCKET: Driver sends location ----------------
@socketio.on('driver_location')
def handle_driver_location(data):
    driver_id = data.get('driver_id')
    lat = data.get('lat')
    lng = data.get('lng')
    driver_locations[driver_id] = (lat, lng)

    # If you want to save/update in DB
    cursor = db.cursor(buffered=True)
    cursor.execute(
        "UPDATE drivers SET lat=%s, lng=%s WHERE id=%s",
        (lat, lng, driver_id)
    )
    db.commit()
    cursor.close()

    emit('location_update', {'driver_id': driver_id, 'lat': lat, 'lng': lng}, broadcast=True)


# ---------------- FEE CALCULATION ----------------
def calculate_fee(student_lat, student_lng, college_lat, college_lng):
    distance_km = geodesic((student_lat, student_lng), (college_lat, college_lng)).km
    base_fare = 50
    per_km = 8
    return round(base_fare + per_km * distance_km, 2)


# ---------------- MAIN ----------------
if __name__ == '__main__':
    socketio.run(app, debug=True)
