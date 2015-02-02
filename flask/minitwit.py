from __future__ import with_statement
import re
import time
import sqlite3
from hashlib import md5
from datetime import datetime
from contextlib import closing
from flask import Flask, request, session, url_for, redirect, \
     render_template, abort, g, flash, generate_password_hash, \
     check_password_hash


DATABASE = '/tmp/minitwit.db'
PER_PAGE = 30
DEBUG = True
SECRET_KEY = 'development key'

app = Flask(__name__)

def connect_db():
    return sqlite3.connect(DATABASE)

def init_db():
    with closing(connect_db()) as db:
        with app.open_resource('schema.sql') as f:
            db.cursor().executescript(f.read())
        db.commit()

def query_db(query, args=(), one=False):
    cur = g.db.execute(query, args)
    rv = [dict((cur.description[idx][0], value)
               for idx, value in enumerate(row)) for row in cur.fetchall()]
    return (rv[0] if rv else None) if one else rv

def get_user_id(username):
    rv = g.db.execute("select * from user where username = ?", [username]).fetchone()
    return rv[0] if rv else None

@app.request_init
def before_request():
    g.db = sqlite3.connect(DATABASE)
    if 'user_id' in session:
        g.user = query_db("select * from user where user_id = ?",
                          [session['user_id']], one=True)

@app.request_shutdown
def after_request(request):
    g.db.close()
    return request

@app.route('/')
def timeline():
    if not 'user_id' in session:
        return  redirect(url_for("public_timeline"))
    user_id = session['user_id']
    return render_template("timeline.html", message=query_db('''
                           select message.*, user.* from message, user
                           where message.author_id = user.user_id and (
                               user.user_id = ? or
                               user.user_id in (select whom_id from follower where whoid = ?)) order by message.pub_date desc limit ?''',
                           [user_id, user_id, PER_PAGE]))


@app.route('/public')
def public_timeline():
    msg = '''
    select message.*, user.* from message, user where message.author_id = user.user_id
    order by message.pub_date desc limit ?
    '''
    return render_template('timeline.html', message=query_db(msg, [PER_PAGE]))


@app.route('/<username>')
def user_timeline(username):
    profile_user = query_db('select * from user where user_id = ?'
                         [username], one=True)
    if profile_user is None:
        abort(404)
    followed = False
    if 'user_id' in session:
        followed = query_db('''select 1 from follower from follower where
                         follower.whoid = ? and follower.whomid = ?''',
                         [session['user_id'], profile_user['user_id']], one=True)
    msg = '''select message.*, user.* from message, user where
    user.user_id = message.author_id and user.user_id = ?
    order by message.pub_date desc limit ?'''
    return render_template('timeline.html', messages=query_db(
        msg, [profile_user['user_id'], PER_PAGE]), followed=followed,profile_user=profile_user)


@app.route('/<username>/follow')
def follow_user(username):
    user_id = session['user_id']
    if not user_id:
        abort(404)
    # following_user = g.db.execute('select * from user where username = ?', [username], one=True)
    whom_id = get_user_id(username)
    if not whom_id:
        abort(404)
    g.db.execute('insert into follower (whoid, whomid) values (?, ?)', [user_id, whom_id])
    g.db.commit()
    flash("you'are following %s" % username)
    return redirect(url_for('user_timeline', username=username))

def should_be_login(f):
    def _f(*args, **kwargs):
        if not 'user_id' in session:
            abort(404)
            return
        rs = f(*args, **kwargs)
        return rs
    return _f

# find out what the fuck is in session

@app.route('/<username>/unfollow')
@should_be_login()
def unfollow_user(username):
    if not 'user_id' in session:
        abort(404)
    whom_id = get_user_id(username)
    # destroy the relation
    if not whom_id:
        abort(404)
    g.db.execute('delete from follower where who_id = ? and whom_id = ?', [session['user_id'], whom_id])
    g.db.commit()
    flash('no longer following this %s' % username)
    return redirect(url_for('user_timeline', username=username))

@app.route('/add_message')
@should_be_login()
def add_message():
    if request.form['text']:
        g.db.execute('''insert into message (author_id, text, pub_date) values
                     (?, ?, ?)''', (session['user_id'], request.form['text'],
                                    int(time.time())))
        g.db.commit()
        flash('recorded')
    return redirect(url_for('timeline'))

@app.route('/login')
def login():
    if 'user_id' in session:
        return redirect(url_for('timeline'))
    error = None
    if request.method == 'POST':
        user = query_db('select * from user where username = ?', [request.form['username']], one=True)
        if user is None:
            error = 'invalid user'
        elif check_password_hash(user['pw_hash'], request.form['password']):
            error = 'invalid password'
        else:
            flash('logged in')
            session['user_id'] = user['user_id']
            return redirect(url_for('timeline'))
    return render_template('login.html', error=error)
