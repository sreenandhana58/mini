from flask import Flask, render_template, request, redirect, session, flash, url_for
from flask_socketio import SocketIO, emit, join_room
from geopy.distance import geodesic
import mysql.connector
from mysql.connector import Error

# ---------------- APP SETUP ----------------
app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app)

# ---------------- DATABASE CONNECTION ----------------
DB_CONNECTION = mysql.connector.connect(
    host="localhost",
    user="root",
    password="132003",
    database="camp_ride"
)

# ---------------- IN-MEMORY STORAGE ----------------
driver_locations = {}

# ---------------- SOCKET EVENTS ----------------
@socketio.on('connect')
def handle_connect():
    print("User connected", request.sid)

@socketio.on('join_room')
def handle_join_room(data):
    driver_id = data.get("driver_id")
    if driver_id:
        room = f"driver_{driver_id}"
        join_room(room)
        print(f"User {request.sid} joined room: {room}")

@socketio.on('driver_location')
def handle_driver_location(data):
    driver_id = data.get("driver_id")
    lat = data.get("lat")
    lng = data.get("lng")

    driver_locations[driver_id] = (lat, lng)

    cursor = DB_CONNECTION.cursor()
    cursor.execute("UPDATE drivers SET lat=%s, lng=%s WHERE id=%s", (lat, lng, driver_id))
    DB_CONNECTION.commit()
    cursor.close()

    # Broadcast to the specific driver's room
    emit('location_update', {'driver_id': driver_id, 'lat': lat, 'lng': lng}, room=f"driver_{driver_id}")

@socketio.on('stop_location_sharing')
def handle_stop_location_sharing(data):
    driver_id = data.get("driver_id")
    if driver_id in driver_locations:
        del driver_locations[driver_id]

    try:
        cursor = DB_CONNECTION.cursor()
        cursor.execute("UPDATE drivers SET lat=NULL, lng=NULL WHERE id=%s", (driver_id,))
        DB_CONNECTION.commit()
        cursor.close()
    except Error as e:
        print(f"Database error on stop sharing: {e}")
    # Broadcast to the specific driver's room
    emit('location_stop', {"driver_id": driver_id}, room=f"driver_{driver_id}")

# ---------------- ROUTES ----------------
@app.route('/')
def home():
    return render_template('home.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        name = request.form['name']
        password = request.form['password']

        cursor = DB_CONNECTION.cursor(dictionary=True, buffered=True)
        cursor.execute("SELECT * FROM users WHERE name=%s", (name,))
        user = cursor.fetchone()
        cursor.close()

        if not user:
            flash("User not found.", 'danger')
            return redirect(url_for('login'))

        if user['password'] == password:
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            session['user_email'] = user['email']
            session['role'] = user['role']
            session['is_admin'] = (user['role'].lower() == "admin")
            flash("Login successful!", 'success')

            if user['role'].lower() == "driver":
                return redirect(url_for('driver_panel'))
            elif user['role'].lower() == "admin":
                return render_template('admin.html', name=session.get('user_name'))
            else:
                return redirect(url_for('student_panel'))
        else:
            flash("Invalid username or password.", 'danger')
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        role = request.form['role']
        password = request.form['password']

        cursor = DB_CONNECTION.cursor(buffered=True)
        try:
            cursor.execute(
                "INSERT INTO users (name, email, password, role) VALUES (%s, %s, %s, %s)",
                (name, email, password, role)
            )
            DB_CONNECTION.commit()
            flash("Registration successful! Please log in.", 'success')
            
            if role.lower() == "driver":
                return redirect(url_for('driver_bus')) 
            else:
                return redirect(url_for('login'))

        except mysql.connector.Error as e:
            DB_CONNECTION.rollback()
            flash(f"Error during registration: {e}", 'danger')
            return redirect(url_for('register'))

        finally:
            cursor.close()

    return render_template('register.html')

# The route was previously '/admin/add_route', but now uses the simpler '/add_route'.
@app.route('/add_route', methods=['GET', 'POST'])
def manage_routes():
    """Allows admin to add a new bus route. Function name is 'manage_routes'."""
    # NOTE: Add admin role check if deployed in production

    if request.method == 'POST':
        route_no = request.form.get('route_no')
        route_name = request.form.get('route_name')
        starting_point = request.form.get('starting_point')
        destination = request.form.get('destination')
        stops_covered = request.form.get('stops_covered')
        departure_time = request.form.get('departure_time')
        arrival_time = request.form.get('arrival_time')
        driver = request.form.get('driver')
        contact = request.form.get('contact')

        if not (route_no and route_name and starting_point and destination):
            flash('Please fill all mandatory fields.', 'danger')
            # Correctly redirects to its own endpoint function name
            return redirect(url_for('manage_routes')) 

        try:
            cursor = DB_CONNECTION.cursor(buffered=True) 
            cursor.execute("""
                INSERT INTO routes
                (route_no, route_name, starting_point, destination,
                 stops_covered, departure_time, arrival_time, driver, contact)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (route_no, route_name, starting_point, destination,
                  stops_covered, departure_time, arrival_time, driver, contact))
            DB_CONNECTION.commit()
            flash('✅ Route added successfully!', 'success')
            # Redirects to the view_routes endpoint function
            return redirect(url_for('view_routes')) 
        except Error as e: 
            DB_CONNECTION.rollback()
            flash(f'Database Error: {e}', 'danger')
        finally:
            cursor.close()

    return render_template('manage_routes.html')

# 3️⃣ View All Routes (Consolidated from list_routes and the previous view_routes placeholder)
@app.route('/routes')
def view_routes():
    """Displays all routes in a table (for students). Function name is 'view_routes'."""
    try:
        cursor = DB_CONNECTION.cursor(dictionary=True, buffered=True)
        cursor.execute("SELECT * FROM routes ORDER BY route_no ASC")
        routes = cursor.fetchall()
    except Error as e:
        flash(f'Error loading routes: {e}', 'danger')
        routes = []
    finally:
        cursor.close()

    return render_template('view_routes.html', routes=routes)

@app.route('/bus_registration')
def bus_registration():
    """Fetches bus routes and pickup points, and renders the student bus registration form."""
    route_names = []
    pickup_points = []
    
    # Check if DB_CONNECTION is valid before proceeding
    if not DB_CONNECTION.is_connected():
        flash("Database connection error. Routes cannot be loaded.", "danger")
        return render_template('bus_registration.html', routes=[], pickup_points=[])

    cursor = DB_CONNECTION.cursor(dictionary=True, buffered=True)
    
    try:
        # 1. Fetch all unique route names (for the Bus Route dropdown)
        cursor.execute("SELECT DISTINCT route_name FROM routes ORDER BY route_name")
        route_names = [row['route_name'] for row in cursor.fetchall()]

        # 2. Fetch and process all unique pickup points/stops
        cursor.execute("SELECT DISTINCT stops_covered FROM routes WHERE stops_covered IS NOT NULL")
        
        raw_stops = cursor.fetchall()
        all_stops = set()
        for row in raw_stops:
            # Assumes 'stops_covered' is a comma-separated string
            if row['stops_covered']:
                stops_list = row['stops_covered'].split(',')
                for stop in stops_list:
                    all_stops.add(stop.strip())
        
        pickup_points = sorted(list(all_stops))
        
        if not route_names:
             flash("No bus routes found in the database. Please contact the administrator.", "warning")
             
    except Error as e:
        flash(f"Database Query Error: {e}", "danger")
        # Ensure empty lists are passed even on error
        route_names = []
        pickup_points = []
        
    finally:
        cursor.close()

    # Crucial step: Pass BOTH lists to the template with the correct variable names.
    return render_template(
        'bus_registration.html', 
        routes=route_names,           
        pickup_points=pickup_points   
    )
@app.route('/bus_register', methods=['POST'])
def bus_register():
    name = request.form.get('name')
    register_number = request.form.get('register_number')
    department = request.form.get('department')
    year = request.form.get('year')
    email = request.form.get('email')
    phone = request.form.get('phone')
    address = request.form.get('address')
    pickup_point = request.form.get('pickup_point')
    bus_route = request.form.get('bus_route')

    cursor = DB_CONNECTION.cursor(buffered=True)
    try:
        cursor.execute("""
            INSERT INTO students (name, register_number, department, year, email, phone, address, pickup_point, bus_route)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (name, register_number, department, year, email, phone, address, pickup_point, bus_route))
        DB_CONNECTION.commit()
        flash("Bus registration successful!", "success")
        return redirect(url_for('student_panel'))

    except mysql.connector.IntegrityError:
        DB_CONNECTION.rollback()
        flash("Email or register number already exists!", "danger")
        return redirect(url_for('bus_registration'))

    except Exception as e:
        DB_CONNECTION.rollback()
        flash(f"An error occurred: {str(e)}", "danger")
        return redirect(url_for('bus_registration'))

    finally:
        cursor.close()



@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/manage_drivers', methods=['GET'])

def manage_drivers():
    cursor = DB_CONNECTION.cursor(dictionary=True, buffered=True)
    cursor.execute("SELECT * FROM drivers")
    drivers = cursor.fetchall()
    cursor.close()
    return render_template('manage_drivers.html', drivers=drivers)

@app.route('/update_driver/<int:id>', methods=['POST'])
def update_driver(id):
    name = request.form.get('name')
    email = request.form.get('email')
    phone = request.form.get('phone')
    license_number = request.form.get('license_number')
    bus_number = request.form.get('bus_number')
    bus_route = request.form.get('bus_route')

    cursor = DB_CONNECTION.cursor(buffered=True)
    try:
        cursor.execute("""
            UPDATE drivers
            SET name=%s, email=%s, phone=%s, license_number=%s, bus_number=%s, bus_route=%s
            WHERE id=%s
        """, (name, email, phone, license_number, bus_number, bus_route, id))
        DB_CONNECTION.commit()
        flash("Driver updated successfully!", "success")
    except Exception as e:
        DB_CONNECTION.rollback()
        flash(f"Error updating driver: {str(e)}", "danger")
    finally:
        cursor.close()

    return redirect(url_for('manage_drivers'))

@app.route('/manage_students', methods=['GET'])
def manage_students():
    cursor = DB_CONNECTION.cursor(dictionary=True, buffered=True)
    cursor.execute("SELECT * FROM students")
    students = cursor.fetchall()
    cursor.close()
    return render_template('manage_students.html', students=students)

@app.route('/update_student/<int:id>', methods=['POST'])
def update_student(id):
    name = request.form.get('name')
    email = request.form.get('email')
    phone = request.form.get('phone')
    pickup_point = request.form.get('pickup_point')
    bus_route = request.form.get('bus_route')

    cursor = DB_CONNECTION.cursor(buffered=True)
    try:
        cursor.execute("""
            UPDATE students
            SET name=%s, email=%s, phone=%s, pickup_point=%s, bus_route=%s
            WHERE id=%s
        """, (name, email, phone, pickup_point, bus_route, id))
        DB_CONNECTION.commit()
        flash("Student updated successfully!", "success")
    except Exception as e:
        DB_CONNECTION.rollback()
        flash(f"Error updating student: {str(e)}", "danger")
    finally:
        cursor.close()

    return redirect(url_for('manage_students'))

@app.route('/approve_student/<int:id>', methods=['POST'])
def approve_student(id):
    if 'user_id' not in session or session.get('role') != 'driver':
        flash("You are not authorized to perform this action.", "danger")
        return redirect(url_for('login'))
    try:
        cursor = DB_CONNECTION.cursor(buffered=True)
        cursor.execute("UPDATE students SET status='approved' WHERE id=%s", (id,))
        DB_CONNECTION.commit()
        flash("Student approved successfully!", "success")
    except Error as e:
        DB_CONNECTION.rollback()
        flash(f"Database error: {e}", "danger")
    finally:
        cursor.close()
    return redirect(url_for('driver_panel'))

@app.route('/reject_student/<int:id>', methods=['POST'])
def reject_student(id):
    if 'user_id' not in session or session.get('role') != 'driver':
        flash("You are not authorized to perform this action.", "danger")
        return redirect(url_for('login'))
    try:
        cursor = DB_CONNECTION.cursor(buffered=True)
        cursor.execute("DELETE FROM students WHERE id=%s AND status='pending'", (id,))
        DB_CONNECTION.commit()
        flash("Student registration rejected.", "info")
    except Error as e:
        DB_CONNECTION.rollback()
        flash(f"Database error: {e}", "danger")
    finally:
        cursor.close()
    return redirect(url_for('driver_panel'))

@app.route('/feedback', methods=['GET', 'POST'])
def feedback():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        message = request.form['message']

        cursor = DB_CONNECTION.cursor(buffered=True)
        try:
            cursor.execute("INSERT INTO feedback (name, email, message) VALUES (%s, %s, %s)",
                           (name, email, message))
            DB_CONNECTION.commit()
        finally:
            cursor.close()
        
        flash("Thank you for your feedback!", 'success')
        return redirect(url_for('feedback'))
    return render_template('feedback.html')

@app.route('/view_feedbacks')
def view_feedbacks():
    cursor = DB_CONNECTION.cursor(dictionary=True, buffered=True)
    cursor.execute("SELECT * FROM feedback")
    feedbacks = cursor.fetchall()
    cursor.close()
    if session['role'].lower() == "admin":
        return render_template('view_feedbacks.html', feedbacks=feedbacks)
    else:
        flash("You are not authorized to perform this action.", "danger")
        return redirect(url_for('student_panel'))



@app.route('/student_panel')





def student_panel():
    if 'user_id' not in session:
        flash("Please log in first.", 'warning')
        return redirect(url_for('login'))

    driver_id = None
    driver_lat = 9.9312  # Default latitude
    driver_lng = 76.2673 # Default longitude
    student_status = None
    is_sharing = False # New flag to track if driver is sharing
    driver = None # Will hold driver details
    try:
        cursor = DB_CONNECTION.cursor(dictionary=True, buffered=True)
        # First, find the student's bus route using their email
        cursor.execute("SELECT bus_route, status FROM students WHERE email = %s", (session['user_email'],))
        student = cursor.fetchone()
        
        if not student:
            flash("You have not registered for bus service yet.", "warning")
            return render_template('student.html', name=session.get('user_name'), driver_id=None, student_status='unregistered')

        student_status = student['status']

        # Only fetch driver location if the student is approved
        if student_status == 'approved' and student.get('bus_route'):
            # Then, find the driver assigned to that route
            cursor.execute("SELECT id, name, phone, bus_number, lat, lng FROM drivers WHERE bus_route = %s", (student['bus_route'],))
            driver = cursor.fetchone()
            if driver:
                driver_id = driver['id']
                # Use driver's location if available, otherwise use default
                if driver.get('lat') and driver.get('lng'):
                    driver_lat = driver['lat']
                    driver_lng = driver['lng']
                    is_sharing = True # Driver has a location, so they are sharing
        
    except Error as e:
        flash(f"Could not retrieve driver information: {e}", "danger")
    finally:
        if 'cursor' in locals() and cursor:
            cursor.close()

    return render_template('student.html',
                           name=session.get('user_name'),
                           driver_id=driver_id,
                           driver_lat=driver_lat,
                           driver_lng=driver_lng,
                           student_status=student_status,
                           is_sharing=is_sharing,
                           driver=driver)


@app.route('/payment')
def payment():
 return render_template('payment.html')


@app.route('/driver_panel')
def driver_panel():
    if 'user_email' not in session:
        flash("Please log in first.", 'warning')
        return redirect(url_for('login'))

    cursor = DB_CONNECTION.cursor(dictionary=True, buffered=True)
    cursor.execute("SELECT * FROM drivers WHERE email = %s", (session['user_email'],))
    driver = cursor.fetchone()

    if not driver:
        cursor.close()
        flash("Driver details not found. Please register your bus details.", 'warning')
        return redirect(url_for('driver_bus'))

    cursor.execute("SELECT * FROM students WHERE bus_route = %s", (driver['bus_route'],))
    students = cursor.fetchall()
    cursor.close()

    return render_template(
        'driver_panel.html',
        driver=driver,
        students=students,
        name=session.get('user_name'),
        driver_lat=driver.get('lat') or 9.9312,  # Default to Kochi if NULL
        driver_lng=driver.get('lng') or 76.2673 # Default to Kochi if NULL
    )

@app.route('/edit_driver_details', methods=['POST'])
def edit_driver_details():
    """Allows a logged-in driver to edit their own details."""
    if 'user_id' not in session or session.get('role') != 'driver':
        flash("You are not authorized to perform this action.", "danger")
        return redirect(url_for('login'))

    driver_id = session.get('user_id') # Assuming user_id corresponds to driver's user id
    driver_email = session.get('user_email')

    name = request.form.get('name')
    phone = request.form.get('phone')
    license_number = request.form.get('license_number')
    bus_number = request.form.get('bus_number')

    try:
        cursor = DB_CONNECTION.cursor(buffered=True)
        cursor.execute("""
            UPDATE drivers SET name=%s, phone=%s, license_number=%s, bus_number=%s
            WHERE email=%s
        """, (name, phone, license_number, bus_number, driver_email))
        DB_CONNECTION.commit()
        flash("Your details have been updated successfully!", "success")
    except Error as e:
        DB_CONNECTION.rollback()
        flash(f"Database error: {e}", "danger")
    finally:
        cursor.close()
    return redirect(url_for('driver_panel'))

@app.route('/driver_bus', methods=['GET', 'POST'])
def driver_bus():
    if 'user_email' not in session:
        flash("Please log in first to register bus details.", 'warning')
        return redirect(url_for('login'))

    route_names = []
    cursor = DB_CONNECTION.cursor(dictionary=True, buffered=True) # Use dictionary=True for named columns
    try:
        # Fetch all unique route names from the routes table
        cursor.execute("SELECT DISTINCT route_name FROM routes ORDER BY route_name")
        route_names = [row['route_name'] for row in cursor.fetchall()]
    except Error as e:
        flash(f"Error loading routes: {e}", "danger")
    finally:
        cursor.close()

    if request.method == 'POST':
        driver_name = request.form['driverName']
        driver_email = request.form['driverEmail']
        driver_phone = request.form['driverPhone']
        driver_license = request.form['driverLicense']
        bus_number = request.form['busNumber']
        # The value of 'busRoute' now comes from the select dropdown
        bus_route = request.form['busRoute'] 

        if driver_email != session['user_email']:
             flash("Email mismatch with logged-in user. Using logged-in email.", 'warning')
             driver_email = session['user_email']

        cursor = DB_CONNECTION.cursor(buffered=True)
        try:
            cursor.execute("SELECT id FROM drivers WHERE email = %s", (driver_email,))
            if cursor.fetchone():
                flash("Bus details for this driver email already exist. Use 'manage_drivers' to update.", 'warning')
                return redirect(url_for('driver_panel'))

            cursor.execute("""
                INSERT INTO drivers (name, email, phone, license_number, bus_number, bus_route)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (driver_name, driver_email, driver_phone, driver_license, bus_number, bus_route))
            DB_CONNECTION.commit()
            flash("Driver and Bus details added successfully!", "success")
            return redirect(url_for('driver_panel'))
        except mysql.connector.Error as err:
            DB_CONNECTION.rollback()
            flash(f"Error: {err}", "danger")
        finally:
            cursor.close()

    # Pass the fetched route names to the template for both GET and failed POST requests
    return render_template(
        'driver_bus.html', 
        driver_email=session.get('user_email'),
        route_names=route_names # <-- NEW: Passing the list of route names
    )

@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", 'success')
    return redirect(url_for('login'))

# ---------------- MAIN ----------------
if __name__ == '__main__':
    socketio.run(app, debug=True)