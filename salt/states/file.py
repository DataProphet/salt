'''
Manage file states
'''

import os
import shutil
import tempfile
import difflib
import hashlib
import traceback

def _makedirs(path):
    '''
    Ensure that the directory containing this path is available.
    '''
    if not os.path.isdir(os.path.dirname(path)):
        os.makedirs(os.path.dirname(path))

def _is_bin(path):
    '''
    Return True if a file is a bin, just checks for NULL char, this should be
    expanded to reflect how git checks for bins
    '''
    if open(path, 'rb').read(2048).count('\0'):
        return True
    return False

def _mako(sfn):
    '''
    Render a jinja2 template, returns the location of the rendered file,
    return False if render fails.
    Returns:
        {'result': bool,
         'data': <Error data or rendered file path>}
    '''
    try:
        from mako.template import Template
    except ImportError:
        return {'result': False,
                'data': 'Failed to import jinja'}
    try:
        tgt = tempfile.mkstemp()[1]
        passthrough = {}
        passthrough.update(__salt__)
        passthrough.update(__grains__)
        template = Template(open(sfn, 'r').read())
        open(tgt, 'w+').write(template.render(**passthrough))
        return {'result': True,
                'data': tgt}
    except:
        trb = traceback.format_exc()
        return {'result': False,
                'data': trb}

def _jinja(sfn):
    '''
    Render a jinja2 template, returns the location of the rendered file,
    return False if render fails.
    Returns:
        {'result': bool,
         'data': <Error data or rendered file path>}
    '''
    try:
        from jinja2 import Template
    except ImportError:
        return {'result': False,
                'data': 'Failed to import jinja'}
    try:
        tgt = tempfile.mkstemp()[1]
        passthrough = {}
        passthrough['salt'] = __salt__
        passthrough['grains'] = __grains__
        template = Template(open(sfn, 'r').read())
        open(tgt, 'w+').write(template.render(**passthrough))
        return {'result': True,
        	    'data': tgt}
    except:
        trb = traceback.format_exc()
        return {'result': False,
                'data': trb}

def symlink(name, target, force=False, makedirs=False):
    '''
    Create a symlink
    '''
    ret = {'name': name,
           'changes': {},
           'result': True,
           'comment': ''}
    if not os.path.isdir(os.path.dirname(name)):
        if makedirs:
            _makedirs(name)
        ret['result'] = False
        ret['comment'] = 'Directory {0} for symlink is not present'.format(os.path.dirname(name))
        return ret
    if os.path.islink(name):
        # The link exists, verify that it matches the target
        if not os.readlink(name) == target:
            # The target is wrong, delete the link
            os.remove(name)
        else:
            # The link looks good!
            ret['comment'] = 'The symlink {0} is present'.format(name)
            return ret
    elif os.path.isfile(name):
        # Since it is not a link, and is a file, error out
        if force:
            os.remove(name)
        else:
            ret['result'] = False
            ret['comment'] = 'File exists where the symlink {0} should be'.format(name)
            return ret
    elif os.path.isdir(name):
        # It is not a link or a file, it is a dir, error out
        if force:
            shutil.rmtree(name)
        else:
            ret['result'] = False
            ret['comment'] = 'Direcotry exists where the symlink {0} should be'.format(name)
            return ret
    if not os.path.exists(name):
        # The link is not present, make it
        os.symlink(target, name)
        ret['comment'] = 'Created new symlink {0}'.format(name)
        ret['changes']['new'] = name
        return ret

def absent(name):
    '''
    Verify that the named file or directory is absent
    '''
    ret = {'name': name,
           'changes': {},
           'result': True,
           'comment': ''}
    if os.path.isfile(name) or os.path.islink(name):
        try:
            os.remove(name)
            ret['comment'] = 'Removed file {0}'.format(name)
            ret['changes']['removed'] = name
            return ret
        except:
            ret['result'] = False
            ret['comment'] = 'Failed to remove file {0}'.format(name)
            return ret
    elif os.path.isdir(name):
        try:
            shutil.rmtree(name)
            ret['comment'] = 'Removed directory {0}'.format(name)
            ret['changes']['removed'] = name
            return ret
        except:
            ret['result'] = False
            ret['comment'] = 'Failed to remove directory {0}'.format(name)
            return ret
    ret['comment'] = 'File {0} is not present'.format(name)
    return ret

def managed(name,
        source,
        user=None,
        group=None,
        mode=None,
        template=None,
        makedirs=False,
        __env__='base'):
    '''
    Manage a given file
    '''
    if mode:
        mode = str(mode)
    ret =  {'name': name,
            'changes': {},
            'result': True,
            'comment': ''}
    # Check changes if the target file exists
    if os.path.isfile(name):
        # Check sums
        source_sum = __salt__['cp.hash_file'](source, __env__)
        if not source_sum:
            ret['result'] = False
            ret['comment'] = 'Source file {0} not found'.format(source)
            return ret
        name_sum = getattr(hashlib, source_sum['hash_type'])(open(name,
            'rb').read()).hexdigest()
        # Check if file needs to be replaced
        if source_sum['hsum'] != name_sum:
            sfn = __salt__['cp.cache_file'](source, __env__)
            if not sfn:
                ret['result'] = False
                ret['comment'] = 'Source file {0} not found'.format(source)
                return ret
            # If the source file is a template render it accordingly
            if template:
                t_key = '_' + template
                if globals().has_key(t_key):
                    data = globals()[t_key](sfn)
                if data['result']:
                    sfn = data['data']
                else:
                    ret['result'] = False
                    ret['comment'] = data['data']
                    return ret
            # Check to see if the files are bins
            if _is_bin(sfn) or _is_bin(name):
                ret['changes']['diff'] = 'Replace binary file'
            else:
                slines = open(sfn, 'rb').readlines()
                nlines = open(name, 'rb').readlines()
                ret['changes']['diff'] = '\n'.join(difflib.unified_diff(slines, nlines))
            # Pre requs are met, and the file needs to be replaced, do it
            if not __opts__['test']:
                shutil.copy(sfn, name)
        # Check permissions
        perms = {}
        perms['luser'] = __salt__['file.get_user'](name)
        perms['lgroup'] = __salt__['file.get_group'](name)
        perms['lmode'] = __salt__['file.get_mode'](name)
        # Run through the perms and detect and apply the needed changes
        if user:
            if user != perms['luser']:
                perms['cuser'] = user
        if group:
            if group != perms['lgroup']:
                perms['cgroup'] = group
        if perms.has_key('cuser') or perms.has_key('cgroup'):
            if not __opts__['test']:
                __salt__['file.chown'](
                        name,
                        user,
                        group
                        )
        if mode:
            if mode != perms['lmode']:
                if not __opts__['test']:
                    __salt__['file.set_mode'](name, mode)
                if mode != __salt__['file.get_mode'](name):
                    ret['result'] = False
                    ret['comment'] += 'Mode not changed '
                else:
                    ret['changes']['mode'] = mode
        if user:
            if user != __salt__['file.get_user'](name):
                ret['result'] = False
                ret['comment'] = 'Failed to change user to {0} '.format(user)
            elif perms.has_key('cuser'):
                ret['changes']['user'] = user
        if group:
            if group != __salt__['file.get_group'](name):
                ret['result'] = False
                ret['comment'] += 'Failed to change group to {0} '.format(group)
            elif perms.has_key('cgroup'):
                ret['changes']['group'] = group

        if not ret['comment']:
            ret['comment'] = 'File {0} updated'.format(name)

        if __opts__['test']:
            ret['comment'] = 'File {0} not updated'.format(name)
        elif not ret['changes'] and ret['result']:
            ret['comment'] = 'File {0} is in the correct state'.format(name)
        return ret
    else:
        # The file is not currently present, throw it down, log all changes
        sfn = __salt__['cp.cache_file'](source, __env__)
        if not sfn:
            ret['result'] = False
            ret['comment'] = 'Source file {0} not found'.format(source)
            return ret
        # Handle any template management that is needed
        if template:
            data = {}
            t_key = '_' + template
            if globals().has_key(t_key):
                data = globals()[t_key](sfn)
            if data.get('result'):
                sfn = data['data']
            else:
                ret['result'] = False
                return ret
        # It is a new file, set the diff accordingly
        ret['changes']['diff'] = 'New file'
        # Apply the new file
        if not __opts__['test']:
            if makedirs:
                _makedirs(name)
            shutil.copy(sfn, name)
        # Check permissions
        perms = {}
        perms['luser'] = __salt__['file.get_user'](name)
        perms['lgroup'] = __salt__['file.get_group'](name)
        perms['lmode'] = __salt__['file.get_mode'](name)
        # Run through the perms and detect and apply the needed changes to
        # permissions
        if user:
            if user != perms['luser']:
                perms['cuser'] = user
        if group:
            if group != perms['lgroup']:
                perms['cgroup'] = group
        if perms.has_key('cuser') or perms.has_key('cgroup'):
            if not __opts__['test']:
                __salt__['file.chown'](
                        name,
                        user,
                        group
                        )
        if mode:
            if mode != perms['lmode']:
                if not __opts__['test']:
                    __salt__['file.set_mode'](name, mode)
                if mode != __salt__['file.get_mode'](name):
                    ret['result'] = False
                    ret['comment'] += 'Mode not changed '
                else:
                    ret['changes']['mode'] = mode
        if user:
            if user != __salt__['file.get_user'](name):
                ret['result'] = False
                ret['comment'] += 'User not changed '
            elif perms.has_key('cuser'):
                ret['changes']['user'] = user
        if group:
            if group != __salt__['file.get_group'](name):
                ret['result'] = False
                ret['comment'] += 'Group not changed '
            elif perms.has_key('cgroup'):
                ret['changes']['group'] = group

        if not ret['comment']:
            ret['comment'] = 'File ' + name + ' updated'

        if __opts__['test']:
            ret['comment'] = 'File ' + name + ' not updated'
        elif not ret['changes'] and ret['result']:
            ret['comment'] = 'File ' + name + ' is in the correct state'
        return ret

def directory(name,
        user=None,
        group=None,
        mode=None,
        makedirs=False):
    '''
    Ensure that a named directory is present and has the right perms
    '''
    if mode:
        mode = str(mode)
    ret =  {'name': name,
            'changes': {},
            'result': True,
            'comment': ''}
    if os.path.isfile(name):
        ret['result'] = False
        ret['comment'] = 'Specifed location {0} exists and is a file'.format(name)
        return ret
    if not os.path.isdir(name):
        # The dir does not exist, make it
        if not os.path.isdir(os.path.dirname(name)):
            if makedirs:
                _makedirs(name)
            else:
                ret['result'] = False
                ret['comment'] = 'No directory to create {0} in'.format(name)
                return ret
    if not os.path.isdir(name):
        _makedirs(name)
        os.makedirs(name)
    if not os.path.isdir(name):
        ret['result'] = False
        ret['comment'] = 'Failed to create directory {0}'.format(name)
        return ret

    # Check permissions
    perms = {}
    perms['luser'] = __salt__['file.get_user'](name)
    perms['lgroup'] = __salt__['file.get_group'](name)
    perms['lmode'] = __salt__['file.get_mode'](name)
    # Run through the perms and detect and apply the needed changes
    if user:
        if user != perms['luser']:
            perms['cuser'] = user
    if group:
        if group != perms['lgroup']:
            perms['cgroup'] = group
    if perms.has_key('cuser') or perms.has_key('cgroup'):
        if not __opts__['test']:
            __salt__['file.chown'](
                    name,
                    user,
                    group
                    )
    if mode:
        if mode != perms['lmode']:
            if not __opts__['test']:
                __salt__['file.set_mode'](name, mode)
            if mode != __salt__['file.get_mode'](name):
                ret['result'] = False
                ret['comment'] += 'Mode not changed '
            else:
                ret['changes']['mode'] = mode
    if user:
        if user != __salt__['file.get_user'](name):
            ret['result'] = False
            ret['comment'] = 'Failed to change user to {0} '.format(user)
        elif perms.has_key('cuser'):
            ret['changes']['user'] = user
    if group:
        if group != __salt__['file.get_group'](name):
            ret['result'] = False
            ret['comment'] += 'Failed to change group to {0} '.format(group)
        elif perms.has_key('cgroup'):
            ret['changes']['group'] = group

    if not ret['comment']:
        ret['comment'] = 'Directory {0} updated'.format(name)

    if __opts__['test']:
        ret['comment'] = 'Directory {0} not updated'.format(name)
    elif not ret['changes'] and ret['result']:
        ret['comment'] = 'Directory {0} is in the correct state'.format(name)
    return ret

def recurse(name,
        source,
        __env__='base'):
    '''
    Recurse through a subdirectory on the master and copy said subdirecory
    over to the specified path
    '''
    ret = {'name': name,
           'changes': {},
           'result': True,
           'comment': ''}
    # Verify the target directory
    if not os.path.isdir(name):
        if os.path.exists(name):
            # it is not a dir, but it exists - fail out
            ret['result'] = False
            ret['comment'] = 'The path {0} exists and is not a directory'.format(name)
            return ret
        os.makedirs(name)
    for fn_ in __salt__['file.cache_dir'](source, __env__):
        dest = os.path.join(name,
                os.path.relpath(
                    fn_,
                    os.path.join(
                        __opts__['cachedir'],
                        'files',
                        __env__
                        )
                    )
                )
        if not os.path.isdir(os.path.dirname(dest)):
            _makedirs(dest)
        if os.path.isfile(dest):
            # The file is present, if the sum differes replace it
            srch = hashlib.md5(open(fn_, 'r').read()).hexdigest()
            dsth = hashlib.md5(open(dest, 'r').read()).hexdigest()
            if srch != dsth:
                # The downloaded file differes, replace!
                shutil.copy(fn_, dest)
                ret['changes'][dest] = 'updated'
        else:
            # The destination file is not present, make it
            shutil.copy(fn_, dest)
            ret['changes'][dest] = 'new'
    return ret
