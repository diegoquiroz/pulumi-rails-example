import json
import pulumi
from pulumi_aws import ec2, ecr, ecs, lb, iam

# VPC and Networking
vpc = ec2.Vpc(
    "myapp-vpc",
    cidr_block="10.0.0.0/16",
    enable_dns_hostnames=True,
    enable_dns_support=True,
)

public_subnet_1 = ec2.Subnet(
    "public-subnet-1",
    vpc_id=vpc.id,
    cidr_block="10.0.1.0/24",
    availability_zone="us-east-1a",
    map_public_ip_on_launch=True,
)

public_subnet_2 = ec2.Subnet(
    "public-subnet-2",
    vpc_id=vpc.id,
    cidr_block="10.0.2.0/24",
    availability_zone="us-east-1b",
    map_public_ip_on_launch=True,
)

internet_gateway = ec2.InternetGateway("myapp-igw", vpc_id=vpc.id)

route_table = ec2.RouteTable(
    "myapp-rt",
    vpc_id=vpc.id,
    routes=[
        ec2.RouteTableRouteArgs(
            cidr_block="0.0.0.0/0",
            gateway_id=internet_gateway.id,
        )
    ],
)

ec2.RouteTableAssociation(
    "rta-1", subnet_id=public_subnet_1.id, route_table_id=route_table.id
)

ec2.RouteTableAssociation(
    "rta-2", subnet_id=public_subnet_2.id, route_table_id=route_table.id
)

# Security Group
security_group = ec2.SecurityGroup(
    "myapp-sg",
    description="Allow inbound traffic for the Rails app",
    vpc_id=vpc.id,
    ingress=[
        ec2.SecurityGroupIngressArgs(
            protocol="tcp",
            from_port=80,
            to_port=80,
            cidr_blocks=["0.0.0.0/0"],
        )
    ],
    egress=[
        ec2.SecurityGroupEgressArgs(
            protocol="-1",
            from_port=0,
            to_port=0,
            cidr_blocks=["0.0.0.0/0"],
        )
    ],
)

# ECR Repository
ecr_repo = ecr.Repository("myapp-repo", name="myapp-repo")

# ECS Cluster
cluster = ecs.Cluster("myapp-cluster", name="myapp-cluster")

role = iam.Role(
    "myapp-task-exec-role",
    assume_role_policy=json.dumps(
        {
            "Version": "2008-10-17",
            "Statement": [
                {
                    "Sid": "",
                    "Effect": "Allow",
                    "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                }
            ],
        }
    ),
)

# ECS Task Definition
task_definition = ecs.TaskDefinition(
    "myapp-task",
    family="myapp-task-family",
    cpu="256",
    memory="512",
    network_mode="awsvpc",
    requires_compatibilities=["FARGATE"],
    execution_role_arn=role.arn,
    container_definitions=pulumi.Output.json_dumps(
        [
            {
                "name": "myapp",
                "image": ecr_repo.repository_url.apply(lambda url: f"{url}:latest"),
                "portMappings": [
                    {"containerPort": 3000, "hostPort": 3000, "protocol": "tcp"}
                ],
                "secrets": [
                    {
                        "name": "DATABASE_URL",
                        "valueFrom": "arn:aws:ssm:us-east-1:774287600271:parameter/myapp/database_url",
                    }
                ],
            }
        ]
    ),
)

# Application Load Balancer
alb = lb.LoadBalancer(
    "myapp-alb",
    load_balancer_type="application",
    security_groups=[security_group.id],
    subnets=[public_subnet_1.id, public_subnet_2.id],
)

target_group = lb.TargetGroup(
    "myapp-tg", port=80, protocol="HTTP", target_type="ip", vpc_id=vpc.id
)

listener = lb.Listener(
    "myapp-listener",
    load_balancer_arn=alb.arn,
    port=80,
    default_actions=[
        lb.ListenerDefaultActionArgs(
            type="forward",
            target_group_arn=target_group.arn,
        )
    ],
)

# ECS Service with Fargate Spot
service = ecs.Service(
    "myapp-service",
    cluster=cluster.arn,
    desired_count=1,
    task_definition=task_definition.arn,
    network_configuration=ecs.ServiceNetworkConfigurationArgs(
        assign_public_ip=True,
        subnets=[public_subnet_1.id, public_subnet_2.id],
        security_groups=[security_group.id],
    ),
    load_balancers=[
        ecs.ServiceLoadBalancerArgs(
            target_group_arn=target_group.arn,
            container_name="myapp",
            container_port=3000,
        )
    ],
    capacity_provider_strategies=[
        ecs.ServiceCapacityProviderStrategyArgs(
            capacity_provider="FARGATE_SPOT",
            weight=1,
        )
    ],
)

# Outputs
pulumi.export("ecr_repo_url", ecr_repo.repository_url)
pulumi.export("alb_dns_name", alb.dns_name)
