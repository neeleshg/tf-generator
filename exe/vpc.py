#!/usr/bin/env python

import click
import boto3
import shutil
import os
import jinja2
import netaddr


infra_root_path = os.getenv('infra_root_path', '/opt/infra')

infra_template_path = '/data/demo1/terraform_templates/infra'

region_list = ['us-east-1']
envs = ['dev', 'prod', 'default']

infra_template_env = jinja2.Environment(loader=jinja2.FileSystemLoader(infra_template_path))
os.environ['AWS_SHARED_CREDENTIALS_FILE'] = '/etc/aws/creds'

@click.group(chain=True)
def cli():
	pass

def _read_file(path):
	"""
	:param path:
	:return:
	"""
	with open(path, 'r') as f:
		return f.read()

def _write_file(path, text):
	if os.path.exists(path):
		print click.style('File Path: {}'.format(path), fg='red')
		overwrite = click.prompt('Do you want to overwrite this file else .New file will be created', default='no', type=click.Choice(['yes','no']))
		if overwrite == 'yes':
			with open(path, 'w') as f:
				f.write(text)
		else:
			with open(path + '.NEW', 'w') as f:
				f.write(text)
	else:
		with open(path, 'w') as f:
			f.write(text)

def _save_render(template_path, out_path, data):
	print click.style('Converting template from {} to {}'.format(template_path, out_path), fg='green')
	template = infra_template_env.get_template(template_path)
	_write_file(out_path, template.render(data))

def _create_infra_root(data):
	if os.path.exists(infra_root_path + '/{env}/{region}'.format(**data)):
		print click.style('{} exists'.format(infra_root_path + '/{env}/{region}'.format(**data)), fg='yellow')
		return
	os.makedirs(infra_root_path + '/{env}/{region}'.format(**data))

	_save_render('aws/variable.tf.jinja', '{}/{}/variable.tf'.format(infra_root_path, data['env']), data)
	os.symlink('{}/{}/variable.tf'.format(infra_root_path,data['env']),
		                                  '{}/{}/{}/variable.tf'.format(infra_root_path, data['env'], data['region']))

	infra_path = infra_root_path + '/{env}/{region}'.format(**data)
	_save_render('aws/provider.tf.jinja', '{}/provider.tf'.format(infra_path), data)
	_save_render('aws/terraform.tfvars.jinja', '{}/terraform.tfvars'.format(infra_path), data)
        shutil.copytree('{}/scripts'.format(infra_template_path), '{}/scripts'.format(infra_path))

def _gen_ssh_keys(key_path, env, region):
    """

    :param key_path:
    :return:
    """
    key = RSA.generate(2048)
    _write_file(key_path + '/' + env + '-' + region + '.pem', key.exportKey('PEM'))
    os.chmod(key_path + '/' + env + '-' + region + '.pem', 0400)
    pubkey = key.publickey()
    _write_file(key_path + '/' + env + '-' + region + '.pub', pubkey.exportKey('OpenSSH'))
    os.chmod(key_path + '/' + env + '-' + region + '.pub', 0400)

@cli.command('add_vpc', help='Generate Terraform Template for VPC')
@click.option('--env', prompt='Provide Env', type=click.Choice(envs))
@click.option('--region', prompt='Provide Region', type=click.Choice(region_list))
@click.option('--cidr_block', prompt='Provide CIDR Block like 10.0.0.0/16')
@click.option('--mgmt_vpc_id', prompt='Provide Management VPC ID')
@click.pass_context
def addvpc(ctx, env, region, cidr_block, mgmt_vpc_id):
	data = {}
	data['env'] = env
	data['region'] = region
	data['uregion'] = region.replace('-', '_')
	data['cidr_block'] = cidr_block
	session = boto3.Session(profile_name=env, region_name=region)
	ec2 = session.client('ec2')
	AvailabilityZones = [a['ZoneName'] for a in ec2.describe_availability_zones()['AvailabilityZones']]
	data['private'] = []
	data['public'] = []
	data['mgmt_vpc_id'] = mgmt_vpc_id

	network = netaddr.IPNetwork(cidr_block)
	subnets = list(network.subnet(24))
	subnet_count = 0
	data['multi_az'] = click.prompt('Do you want to create subnets in All AZ ?', default='no', type=click.Choice(['yes', 'no']))

	if data['multi_az'] == 'yes':
		for az in AvailabilityZones:
			data['private'].append({'availability_zone': az, 'cidr_block': subnets[subnet_count], 'uaz': az.replace('-', '_')})
			subnet_count =+ 1
			data['public'].append({'availability_zone': az, 'cidr_block': subnets[subnet_count], 'uaz': az.replace('-', '_')})
			subnet_count =+ 1
	else:
		ips = []
		for i in subnets:
			ips.append(str(i.ip))
		data['az'] = click.prompt('Which AZ you want to create Subnet?', default='us-east-1a', type=click.Choice(AvailabilityZones))
		data['cidr_private'] = click.prompt('CIDR for Private subnet?', default=None, type=click.Choice(ips))
		data['cidr_public'] = click.prompt('CIDR for Public subnet?', default=None, type=click.Choice(ips))
		data['private'].append({'availability_zone': data['az'], 'cidr_block': data['cidr_private'] + '/{}'.format(subnets[0].prefixlen), 'uaz': data['az'].replace('-', '_')})
		data['public'].append({'availability_zone': data['az'], 'cidr_block': data['cidr_public'] + '/{}'.format(subnets[0].prefixlen), 'uaz': data['az'].replace('-', '_')})


	data['nat'] = click.prompt('Do you need NAT Gateway?', default='Yes', type=click.Choice(['yes','no']))
	if data['nat'] == 'yes':
		data['multi_nat'] = click.prompt('Do you need NAT per AZ ?', default='no', type=click.Choice(['yes', 'no']))
		data['eip'] = 'auto'
	_create_infra_root(data)
	infra_path = infra_root_path + '/{env}/{region}'.format(**data)
	_save_render('aws/vpc.tf.jinja', '{}/vpc.tf'.format(infra_path) ,data)
	_gen_ssh_keys('{}/{}/{}'.format(infra_root_path, env, region), env, region)
    shutil.copytree('{}/scripts'.format(infra_template_path), '{}/scripts'.format(infra_path))

if __name__ == '__main__':
    cli()
