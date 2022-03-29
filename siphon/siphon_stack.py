import os

from aws_cdk import (
    CustomResource,
    Duration,
    RemovalPolicy,
    Stack,
    aws_dynamodb as _dynamodb,
    aws_ec2 as _ec2,
    aws_events as _events,
    aws_events_targets as _targets,
    aws_iam as _iam,
    aws_lambda as _lambda,
    aws_lambda_event_sources as _sources,
    aws_logs as _logs,
    aws_s3 as _s3,
    aws_s3_deployment as _deployment,
    aws_s3_notifications as _notifications,
    aws_sns as _sns,
    aws_sns_subscriptions as _subscriptions,
    aws_sqs as _sqs,
    aws_ssm as _ssm,
    custom_resources as _custom
)

from constructs import Construct

class SiphonStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

################################################################################

        vpc_id = 'vpc-04eae279ceb94d7f6'    # <-- Enter VPC ID
        
        ec2_count = 1                       # <-- Enter EC2 Quantity
        
        ec2_type = 't3a.small'              # <-- Enter EC2 Size
        
        ebs_root = 8                        # <-- Enter Root Storage GBs

        ebs_data = 4                        # <-- Enter Data Storage GBs

################################################################################

        account = Stack.of(self).account
        region = Stack.of(self).region

### S3 DEPLOYMENT ###

        script_name = 'siphon-'+str(account)+'-scripts-'+region

        os.system('echo "#!/usr/bin/bash" > script/siphon.sh')
        
        os.system('echo "apt-get update" >> script/siphon.sh')
        os.system('echo "apt-get upgrade -y" >> script/siphon.sh')
        
        os.system('echo "apt-get install python3-pip unzip -y" >> script/siphon.sh')
        
        os.system('echo "wget https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip -P /tmp/" >> script/siphon.sh')
        os.system('echo "unzip /tmp/awscli-exe-linux-x86_64.zip -d /tmp" >> script/siphon.sh')
        os.system('echo "/tmp/aws/install" >> script/siphon.sh')
        
        os.system('echo "aws s3 cp s3://'+script_name+'/patch-reboot.sh /root/patch-reboot.sh" >> script/siphon.sh')
        os.system('echo "chmod 750 /root/patch-reboot.sh" >> script/siphon.sh')
        
        os.system('echo "aws s3 cp s3://'+script_name+'/crontab.txt /tmp/crontab.txt" >> script/siphon.sh')
        os.system('echo "cat /tmp/crontab.txt >> /etc/crontab" >> script/siphon.sh')
        
        os.system('echo "DEBIAN_FRONTEND=noninteractive apt-get install postfix -y" >> script/siphon.sh')
        os.system('echo "echo \'deb http://download.opensuse.org/repositories/security:/zeek/xUbuntu_20.04/ /\' | sudo tee /etc/apt/sources.list.d/security:zeek.list" >> script/siphon.sh')
        os.system('echo "curl -fsSL https://download.opensuse.org/repositories/security:zeek/xUbuntu_20.04/Release.key | gpg --dearmor | sudo tee /etc/apt/trusted.gpg.d/security_zeek.gpg > /dev/null" >> script/siphon.sh')
        os.system('echo "apt-get update" >> script/siphon.sh')
        os.system('echo "apt-get install zeek-lts -y" >> script/siphon.sh')
        
        os.system('echo "add-apt-repository ppa:oisf/suricata-stable -y" >> script/siphon.sh')
        os.system('echo "apt-get update" >> script/siphon.sh')
        os.system('echo "apt-get install suricata -y" >> script/siphon.sh')
        
        os.system('echo "pip3 install boto3 requests" >> script/siphon.sh')
        os.system('echo "aws s3 cp s3://'+script_name+'/siphon.py /tmp/siphon.py" >> script/siphon.sh')
        os.system('echo "/usr/bin/python3 /tmp/siphon.py" >> script/siphon.sh')

        script = _s3.Bucket(
            self, 'script',
            bucket_name = script_name,
            encryption = _s3.BucketEncryption.KMS_MANAGED,
            block_public_access = _s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy = RemovalPolicy.DESTROY,
            auto_delete_objects = True,
            versioned = True
        )

        scripts = _deployment.BucketDeployment(
            self, 'scripts',
            sources = [_deployment.Source.asset('script')],
            destination_bucket = script,
            prune = False
        )

### VPC ###

        vpc = _ec2.Vpc.from_lookup(
            self, 'vpc',
            vpc_id = vpc_id
        )

### IAM ###

        role = _iam.Role(
            self, 'role',
            assumed_by = _iam.ServicePrincipal(
                'ec2.amazonaws.com'
            )
        )

        role.add_managed_policy(
            _iam.ManagedPolicy.from_aws_managed_policy_name(
                'AmazonSSMManagedInstanceCore'
            )
        )

        role.add_to_policy(
            _iam.PolicyStatement(
                actions = [
                    's3:GetObject'
                ],
                resources = [
                    script.bucket_arn,
                    script.arn_for_objects('*')
                ]
            )
        )

### SG ###

        management = _ec2.SecurityGroup(
            self, 'management',
            vpc = vpc,
            description = 'siphon-management-eni',
            allow_all_outbound = True
        )

        monitor = _ec2.SecurityGroup(
            self, 'monitor',
            vpc = vpc,
            description = 'siphon-monitor-eni',
            allow_all_outbound = True
        )
        monitor.add_ingress_rule(_ec2.Peer.any_ipv4(), _ec2.Port.udp(4789), 'siphon-monitor-eni')
    
        sgids = []
        sgids.append(monitor.security_group_id)

### SUBNET ###

        subnetids = []
        for subnet in vpc.public_subnets: # vpc.private_subnets
            subnetids.append(subnet.subnet_id)

### EC2 ###

        ### Ubuntu Server 20.04 LTS ###
        ubuntu = _ec2.MachineImage.generic_linux(
            {
                'us-east-1': 'ami-04505e74c0741db8d',
                'us-east-2': 'ami-0fb653ca2d3203ac1',
                'us-west-2': 'ami-0892d3c7ee96c0bf7'
            }
        )

        instanceids = []
        for subnetid in subnetids:
            subnet = _ec2.Subnet.from_subnet_id(
                self, subnetid,
                subnet_id = subnetid
            )
            for i in range(ec2_count):
                instance = _ec2.Instance(
                    self, 'instance-'+subnetid+'-'+str(i),
                    instance_type = _ec2.InstanceType(ec2_type),
                    machine_image = ubuntu,
                    vpc = vpc,
                    vpc_subnets = subnet,
                    role = role,
                    security_group = management,
                    require_imdsv2 = True,
                    propagate_tags_to_volume_on_creation = True,
                    block_devices = [
                        _ec2.BlockDevice(
                            device_name = '/dev/sda1',
                            volume = _ec2.BlockDeviceVolume.ebs(
                                ebs_root,
                                encrypted = True
                            )
                        ),
                        _ec2.BlockDevice(
                            device_name = '/dev/sdf',
                            volume = _ec2.BlockDeviceVolume.ebs(
                                ebs_data,
                                encrypted = True
                            )
                        )
                    ]
                )
                instanceids.append(instance.instance_id)
                network = _ec2.CfnNetworkInterface(
                    self, 'instance-'+subnetid+'-'+str(i)+'-monitor',
                    subnet_id = subnetid,
                    group_set = sgids
                )
                attach = _ec2.CfnNetworkInterfaceAttachment(
                    self, 'instance-'+subnetid+'-'+str(i)+'-attach',
                    device_index = str(1),
                    instance_id = instance.instance_id,
                    network_interface_id = network.ref,
                    delete_on_termination = True
                )
                mirror = _ssm.StringParameter(
                    self, 'instance-'+subnetid+'-'+str(i)+'-mirror',
                    description = 'Siphon ENI Target Mirror(s)',
                    parameter_name = '/siphon/mirror/'+vpc_id+'/'+subnetid+'/instance'+str(i),
                    string_value = network.ref,
                    tier = _ssm.ParameterTier.STANDARD,
                )

### CONFIGURATION ###

        config = _iam.Role(
            self, 'config', 
            assumed_by = _iam.ServicePrincipal(
                'lambda.amazonaws.com'
            )
        )
        
        config.add_managed_policy(
            _iam.ManagedPolicy.from_aws_managed_policy_name(
                'service-role/AWSLambdaBasicExecutionRole'
            )
        )
        
        config.add_to_policy(
            _iam.PolicyStatement(
                actions = [
                    'ssm:SendCommand'
                ],
                resources = [
                    '*'
                ]
            )
        )

        configuration = _lambda.Function(
            self, 'configuration',
            code = _lambda.Code.from_asset('configuration'),
            handler = 'configuration.handler',
            runtime = _lambda.Runtime.PYTHON_3_9,
            timeout = Duration.seconds(30),
            environment = dict(
                INSTANCE = str(instanceids),
                SCRIPTS3 = script_name
            ),
            memory_size = 128,
            role = config
        )
       
        configlogs = _logs.LogGroup(
            self, 'configlogs',
            log_group_name = '/aws/lambda/'+configuration.function_name,
            retention = _logs.RetentionDays.ONE_DAY,
            removal_policy = RemovalPolicy.DESTROY
        )

        provider = _custom.Provider(
            self, 'provider',
            on_event_handler = configuration
        )

        resource = CustomResource(
            self, 'resource',
            service_token = provider.service_token
        )