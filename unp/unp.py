import os
import re
import sys
import tempfile
import mimetypes
import subprocess

import click


FILENAME = object()
OUTPUT_FOLDER = object()
unpackers = []

def register_unpacker(cls):
    unpackers.append(cls)
    return cls

def fnmatch(pattern, filename):
    filename = os.path.basename(os.path.normcase(filename))
    pattern = os.path.normcase(pattern)
    bits = '(%s)' % re.escape(pattern).replace('\\*', ')(.*?)(')
    return re.match('^%s$' % bits, filename)

def which(name):
    path = os.environ['PATH']
    if path:
        for p in path.split(os.pathsep):
            filename = os.path.join(p, name)
            if os.access(filename, os.X_OK):
                return p

def increment_string(string):
    m = re.match(r'(.*?)(\d+)$', string)
    if m is None:
        return string + '-2'
    return m.group(1) + string(int(m.group(2)) + 1)

def get_mimetype(filename):
    file_executable = which('file')
    if file_executable is not None:
        rv = subprocess.Popen(['file', '-b', '--mime-type', filename],
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE).communicate()[0].strip()
        if rv:
            return rv
    return mimetypes.guess_type(filename)[0]


class StreamProcessor(object):
    def __init__(self, format, stream):
        self.regex = re.compile(format)
        self.stream = stream

    def process(self, p):
        stream = getattr(p, self.stream)
        while 1:
            line = stream.readline()
            if not line:
                break
            match = self.regex.search(line)
            if match is not None:
                yield match.group(1)


class UnpackerBase(object):
    name = None
    executable = None
    filename_patterns = ()
    mimetypes = ()
    brew_package = None
    args = ()
    cwd = OUTPUT_FOLDER

    def __init__(self, filename, silent=False):
        self.filename = filename
        self.silent = silent
        self.assert_available()

    @classmethod
    def filename_matches(cls, filename):
        for pattern in cls.filename_patterns:
            if fnmatch(pattern, filename) is not None:
                return True

    @classmethod
    def mimetype_matches(cls, filename):
        mt = get_mimetype(filename)
        return mt in cls.mimetypes

    @classmethod
    def find_executable(cls):
        return which(cls.executable)

    @property
    def basename(self):
        for pattern in self.filename_patterns:
            match = fnmatch(pattern, self.filename)
            if match is None:
                continue
            pieces = match.groups()
            if pieces and pieces[-1].startswith('.'):
                return ''.join(pieces[:-1])
        return os.path.basename(self.filename).split('.', 1)[0]

    def assert_available(self):
        if self.find_executable() is not None:
            return
        msg = ['cannot unpack "%s" cuz %s is not available.' % (
            click.format_filename(self.filename),
            self.executable,
        )]
        if sys.platform == 'darwin' and self.brew_package is not None:
            msg.extend((
                'you can brew install the unpacker threw brew:',
                '',
                '   $ brew install %s' % self.brew_package,
            ))
        raise click.UsageError('\n'.join(msg))

    def get_args_and_cwd(self, dst):
        def convert_arg(arg):
            if arg is FILENAME:
                return self.filename
            if arg is OUTPUT_FOLDER:
                return dst
            return arg

        args = [self.find_executable()]
        for arg in self.args:
            args.append(convert_arg(arg))
        cwd = convert_arg(self.cwd)
        if cwd is None:
            cwd = '.'
        return args, cwd

    def report_file(self, filename):
        if not self.silent:
            click.echo(click.format_filename(filename), err=True)

    def real_unpack(self, dst, silent):
        raise NotImplementedError()

    def finish_unpacking(self, tmp_dir, dst):
        basename = self.basename
        fallback_dst = os.path.join(os.path.abspath(dst), basename)
        while os.path.isdir(fallback_dst):
            fallback_dst = increment_string(fallback_dst)

    
