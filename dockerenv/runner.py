# coding: utf-8

from __future__ import print_function

import sys
import os
import tempfile
import logging
from subprocess import check_call, check_output

from dockerenv.utils import resource, make_tmpdir

'''
                # монтируем base_dir как хомяк, чтобы сохранялся стейт между запусками, например, .bash_history
                '--volume=' + self.base_dir + ':' + self.base_dir + ':rw',

                # монтируем base_dir под тем же именем, что и на хосте, чтобы можно было использовать инструменты
                # отладки на хосте, да и стектрейсы читать удобней
                '--volume=' + self.base_dir + ':' + container_home + ':rw',
'''

class Runner(object):
    def __init__(self, docker_args=(), entrypoint=None):
        self.docker_args = list(docker_args)
        self.entrypoint = entrypoint

    def with_image(self, image):
        return RunnerWithImage(self, image)

    def with_volumes(self, volumes):
        return Runner(
            self.docker_args + [vol.docker_arg() for vol in volumes],
            self.entrypoint,
        )

    def __call__(self, image, cmd, work_dir=None, remove=True):
        basic_docker_args = [
            '--workdir=' + (work_dir or '/'),
        ]

        if self.entrypoint:
            basic_docker_args.append('--entrypoint=' + self.entrypoint)

        if 'SSH_AUTH_SOCK' in os.environ:
            basic_docker_args.extend([
                '--volume=' + os.environ['SSH_AUTH_SOCK'] + ':/run/ssh:rw',
                '--env=SSH_AUTH_SOCK=/run/ssh',
            ])

        try:
            os.ttyname(sys.stdin.fileno())
        except EnvironmentError:
            pass # stdin is not a tty
        else:
            basic_docker_args.extend([
                '--tty',
                '--interactive',
            ])

        def check_call_log(args, level=logging.INFO):
            logging.log(level, args)
            check_call(args, shell=False)

        args = ['docker', 'run'] + basic_docker_args + list(self.docker_args)

        if remove:
            check_call_log(args + ['--rm'] + [image] + cmd)
            return None
        else:
            with make_tmpdir() as tmpdir:
                cidfile = os.path.join(tmpdir, 'cid')
                check_call_log((
                    args + ['--cidfile=' + cidfile]
                    + [image]
                    + cmd
                ))
                with open(cidfile) as cidfobj:
                    return cidfobj.read().strip()


class HostUserRunner(object):
    def __init__(self, docker_args=(), allow_sudo=False):
        self.docker_args = list(docker_args)
        self.allow_sudo = allow_sudo

    def with_image(self, image):
        return RunnerWithImage(self, image)

    def with_volumes(self, volumes):
        return HostUserRunner(
            self.docker_args + [vol.docker_arg() for vol in volumes],
            self.allow_sudo,
        )

    def __call__(self, image, cmd, work_dir=None, remove=True):
        container_username = 'user'
        container_home = '/home/' + container_username

        basic_docker_args = [
            '--env=PATH=' + container_home + '/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
            '--env=HOME=' + container_home,
            '--env=SHELL=' + os.environ.get('SHELL', ''),
            '--env=TERM=' + os.environ.get('TERM', ''),
            '--env=TARGET_USER=' + container_username,
            '--env=TARGET_UID=' + str(os.getuid()),
            '--env=TARGET_GID=' + str(os.getgid()),
            '--volume={}:{}:ro'.format(resource('hostuser_entrypoint.sh'), '/entrypoint'),
            '--volume=' + container_home,
        ]
        if self.allow_sudo:
            basic_docker_args.append('--env=ALLOW_SUDO=1')

        runner = Runner(
            basic_docker_args + self.docker_args,
            entrypoint = '/entrypoint',
        )
        return runner(image, cmd, work_dir, remove)


class RunnerWithImage(object):
    def __init__(self, runner, image):
        self.runner = runner
        self.image = image

    def with_volumes(self, volumes):
        return RunnerWithImage(self.runner.with_volumes(volumes), self.image)

    def __call__(self, cmd, work_dir=None, remove=True):
        return self.runner(self.image, cmd, work_dir, remove)


class NewVolume(object):
    def __init__(self, path):
        self.path

    def docker_arg(self):
        return '--volume=' + path


class Volume(object):
    def __init__(self, host_path, container_path, mode='ro'):
        self.host_path = host_path
        self.container_path = container_path
        self.mode = mode

    def docker_arg(self):
        return '--volume={}:{}:{}'.format(os.path.abspath(self.host_path), self.container_path, self.mode)
