"""Default keywords for the text classifier (task T10).

Format: comma-separated. "word" = whole word, weight 1.  "two words" = phrase, weight 2.
"leak*" = any word starting with "leak".  "hostel:3" = explicit weight.
Hyphens and punctuation are ignored ("Wi-Fi" matches "wi fi").
English and Hinglish (Hindi in Roman letters) are supported; a few Devanagari words are included.

The category keywords live in the database (categories.keywords) so the admin can edit them
without a deploy. These are only the starting values written by `python -m grievance_app.seed`.
The confidential and urgent lists below are in code: change them with a deploy, and test.
"""

DEFAULT_KEYWORDS = {
    "Hostel and housing": (
        "hostel:3, warden:3, caretaker:3, my room:2, hostel room:3, room, bed, mattress, cot, almirah, cupboard, "
        "study table, chair, kursi, fan, pankha, ac, air conditioner, geyser, hot water, tap, flush, bathroom, "
        "wash basin, washbasin, socket, bulb, tube light, tubelight, window, cockroach*, bed bug*, mosquito*, "
        "roommate:1, room allotment:3, allotted"),
    "Campus infrastructure": (
        "classroom:3, class room:3, lecture hall:3, lab:2, laboratory:2, projector:3, bench*, blackboard, whiteboard, "
        "smart board, podium, corridor, staircase, lift:2, elevator:2, drinking water:3, water cooler:3, toilet*, "
        "washroom*, restroom, parking:2, main gate, road, ramp, wheelchair, building, roof, ceiling:2, playground, "
        "street light*:3, streetlight*:3, pothole*, garden, campus"),
    "IT and network": (
        "wifi:4, wi fi:4, internet:4, network:2, net:1, router:4, lan, lms:4, portal:4, moodle:4, erp:4, "
        "college email:4, email id:2, mail:1, password:2, login:2, otp:2, website, vpn:4, server, software:2, "
        "license:2, matlab, laptop, printer, computer:1"),
    "Academics": (
        "attendance:3, timetable:3, time table:3, syllabus:3, course*:2, elective*:3, credit*:2, faculty:2, "
        "professor:2, teacher, lecture*:2, assignment*:1, internal marks:4, internals:2, project guide:3, mentor:2, "
        "curriculum:3, proxy attendance:4, practical classes:3, department:1, class timing*:2, subject*:1"),
    "Examinations": (
        "exam*:3, hall ticket:4, admit card:4, result*:3, revaluation:4, re evaluation:4, answer sheet:4, "
        "question paper:4, grade*:2, cgpa:3, sgpa:3, marksheet:4, mark sheet:4, grade card:4, supplementary:4, "
        "backlog:3, invigilator:4, seating:2, marks:2, exam time table:4, exam timetable:4, re exam:3, "
        "end semester:3, mid semester:3, sem exam*:3"),
    "Fees and accounts": (
        "fee*:3, tuition:3, challan:3, receipt:2, refund:3, payment:2, paid:2, late fee:4, hostel fee:4, "
        "transaction:2, demand draft:3, caution deposit:3, security deposit:3, invoice:2, accounts:2, "
        "money:1, deducted:2, fee structure:4"),
    "Scholarships and documents": (
        "scholarship*:3, bonafide:4, bona fide:4, certificate*:3, transcript:4, id card:4, identity card:4, noc:4, "
        "migration:2, transfer certificate:4, character certificate:4, degree:2, provisional:2, document*:2, "
        "stipend:3, fellowship:3, no dues:4, income certificate:4, caste certificate:4, verification:1"),
    "Library": (
        "library:4, librarian:4, book*:2, borrow*:2, journal*:2, reading room:4, library card:5, e resource*:2, "
        "catalogue:2, catalog:2, renew:1, reference book:3"),
    "Transport": (
        "bus:3, buses:3, transport:3, route:2, bus stop:4, bus timing*:4, driver:3, college bus:4, shuttle:3, "
        "pickup:2, pick up:2, bus pass:4, bus card:4, vehicle:1"),
    "Mess and canteen": (
        "mess:3, canteen:3, food:3, meal*:2, breakfast:2, lunch:2, dinner:2, snacks:2, hygiene:2, dal:2, chapati:2, "
        "roti:2, rice:1, menu:2, cook*:1, kitchen:2, stale:2, tasteless:2, khana:3, nashta:2, tiffin:2"),
    "Harassment, ragging, discrimination, safety": (
        "harass*:5, ragging:5, bully*:5, threat*:5, threaten*:5, assault*:5, abuse*:4, molest*:5, stalk*:5, "
        "discriminat*:5, casteist:5, caste based:5, sexual*:5, touched me:5, inappropriate comment*:4, "
        "inappropriate touch*:5, eve teasing:5, blackmail*:5, hit me:5, beat me:5, suicide:5, self harm:5, "
        "rape*:5, dhamki:5, maar peet:5, mental torture:5, racist:5, unsafe:2, safety:2, "
        "रैगिंग:5, उत्पीड़न:5"),
    "Other": "suggestion*:1, club:1, event*:1, placement:1, general:1",
}

# Any match makes the ticket confidential (handled only by designated officers).
# Prefer false alarms to misses: a false alarm costs an officer a minute, a miss can hurt someone.
CONFIDENTIAL_TERMS = (
    "harass*, ragging, bully*, threat*, threaten*, assault*, abuse*, molest*, stalk*, discriminat*, casteist, "
    "caste based, sexual*, touched me, inappropriate comment*, inappropriate touch*, eve teasing, blackmail*, "
    "hit me, beat me, suicide, self harm, want to die, rape*, dhamki, maar peet, mental torture, racist, "
    "uncomfortable, scared, afraid, following me, followed me, feel unsafe, unsafe, touched, touching me, "
    "रैगिंग, उत्पीड़न"
)

# Any match marks the ticket urgent (a visible flag and an URGENT prefix in notifications).
URGENT_TERMS = (
    "fire, smoke, short circuit, spark*, gas leak, gas smell, electric shock, shock, electrocut*, injur*, bleeding, "
    "ambulance, emergency, flood*, collapse*, snake, stuck in lift, lift stuck, trapped, unconscious, fainted, "
    "medical help, exposed wire, open wire, live wire, burning smell, aag, dhuan, bijli ka jhatka, "
    "threat*, assault*, hit me, beat me, suicide, self harm, want to die, rape*, molest*"
)
