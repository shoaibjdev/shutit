"""Code shared between different modules.
"""

import subprocess
import shutit_pexpect
import pexpect
import os
import logging
from distutils import spawn


# The MIT License (MIT)
#
# Copyright (C) 2014 OpenBet Limited
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of
# this software and associated documentation files (the "Software"), to deal in
# the Software without restriction, including without limitation the rights to
# use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
# of the Software, and to permit persons to whom the Software is furnished to do
# so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# ITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.


def conn_docker_start_container(shutit,shutit_session_name, loglevel=logging.DEBUG):
	docker = shutit.host['docker_executable'].split(' ')
	# Always-required options
	if not os.path.exists(shutit.build['shutit_state_dir'] + '/cidfiles'):
		os.makedirs(shutit.build['shutit_state_dir'] + '/cidfiles')
	shutit.build['cidfile'] = shutit.build['shutit_state_dir'] + '/cidfiles/' + shutit.host['username'] + '_cidfile_' + shutit.build['build_id']
	cidfile_arg = '--cidfile=' + shutit.build['cidfile']
	# Singly-specified options
	privileged_arg   = ''
	name_arg         = ''
	hostname_arg     = ''
	rm_arg           = ''
	net_arg          = ''
	mount_docker_arg = ''
	entrypoint_arg   = '--entrypoint /bin/bash'
	if shutit.build['privileged']:
		privileged_arg = '--privileged=true'
	if shutit.target['name'] != '':
		name_arg = '--name=' + shutit.target['name']
	if shutit.target['hostname'] != '':
		hostname_arg = '-h=' + shutit.target['hostname']
	if shutit.build['net'] != '':
		net_arg        = '--net="' + shutit.build['net'] + '"'
	if shutit.build['mount_docker']:
		mount_docker_arg = '-v=/var/run/docker.sock:/var/run/docker.sock'
	# Incompatible with do_repository_work
	if shutit.target['rm']:
		rm_arg = '--rm=true'
	if shutit.build['base_image'] in ('alpine','busybox'):
		entrypoint_arg = '--entrypoint /bin/ash'
	# Multiply-specified options
	port_args         = []
	dns_args          = []
	volume_args       = []
	volumes_from_args = []
	volumes_list      = shutit.target['volumes'].strip().split()
	volumes_from_list = shutit.target['volumes_from'].strip().split()
	ports_list        = shutit.target['ports'].strip().split()
	dns_list          = shutit.host['dns'].strip().split()
	for portmap in ports_list:
		port_args.append('-p=' + portmap)
	for dns in dns_list:
		dns_args.append('--dns=' + dns)
	for volume in volumes_list:
		volume_args.append('-v=' + volume)
	for volumes_from in volumes_from_list:
		volumes_from_args.append('--volumes-from=' + volumes_from)
	docker_command = docker + [
		arg for arg in [
			'run',
			cidfile_arg,
			privileged_arg,
			name_arg,
			hostname_arg,
			rm_arg,
			net_arg,
			mount_docker_arg,
		] + volume_args + volumes_from_args + port_args + dns_args + [
			'-t',
			'-i',
			entrypoint_arg,
			shutit.target['docker_image']
		] if arg != ''
	]
	shutit.build['docker_command'] = ' '.join(docker_command)
	# docker run happens here
	shutit.log('Startup command is: ' + shutit.build['docker_command'],level=logging.INFO)
	shutit.log('Downloading image, please be patient',level=logging.INFO)
	was_sent = ' '.join(docker_command)
	shutit_pexpect_session = shutit_pexpect.ShutItPexpectSession(shutit_session_name, docker_command[0], docker_command[1:])
	target_child = shutit_pexpect_session.pexpect_child
	expect = ['assword', shutit.expect_prompts['base_prompt'].strip(), 'Waiting', 'ulling', 'endpoint', 'Download','o such file']
	res = shutit_pexpect_session.expect(expect, timeout=9999)
	while True:
		if target_child.before == type(pexpect.exceptions.EOF):
			shutit.fail('EOF exception seen')
		try:
			shutit.log(target_child.before + target_child.after,level=logging.DEBUG)
		except:
			pass
		if res == 0:
			res = shutit.send(shutit.host['password'], shutit_pexpect_child=target_child, expect=expect, timeout=9999, check_exit=False, fail_on_empty_before=False, echo=False, loglevel=loglevel)
		elif res == 1:
			shutit.log('Prompt found, breaking out',level=logging.DEBUG)
			break
		elif res == 6:
			shutit.fail('Docker not installed.')
			break
		elif res == 7:
			shutit.log('Initial command timed out, assuming OK to continue.',level=logging.WARNING)
			break
		elif res == 8:
			shutit.fail('EOF seen.')
		else:
			res = shutit_pexpect_session.expect(expect, timeout=9999)
			continue
	# Did the pull work?
	shutit.log('Checking exit status',level=loglevel)
	if not shutit_pexpect_session._check_last_exit_values(was_sent):
		shutit_global.shutit.pause_point('Command:\n\n' + was_sent + '\n\nfailed, you have a shell to try rectifying the problem before continuing.')
	shutit.log('Getting cid',level=loglevel)
	# Get the cid
	while True:
		try:
			cid = open(shutit.build['cidfile']).read()
			break
		except Exception:
			time.sleep(1)
	if cid == '' or re.match('^[a-z0-9]+$', cid) == None:
		shutit.fail('Could not get container_id - quitting. Check whether other containers may be clashing on port allocation or name.\nYou might want to try running: sudo docker kill ' + shutit.target['name'] + '; sudo docker rm ' + shutit.target['name'] + '\nto resolve a name clash or: ' + shutit.host['docker_executable'] + ' ps -a | grep ' + shutit.target['ports'] + " | awk '{print $1}' | " + 'xargs ' + shutit.host['docker_executable'] + ' kill\nto ' + 'resolve a port clash\n')
	shutit.log('cid: ' + cid,level=logging.DEBUG)
	shutit.target['container_id'] = cid
	return target_child
