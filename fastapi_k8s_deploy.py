from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field, HttpUrl, ValidationError
from kubernetes import client, config
from kubernetes.client.rest import ApiException
import base64
import boto3
from botocore.exceptions import BotoCoreError, ClientError

app = FastAPI()

class KubernetesCredentials(BaseModel):
    kubeconfig: str = Field(..., description="Base64-encoded kubeconfig file")

class DeploymentDetails(BaseModel):
    cluster_name: str
    region: str
    container_image_url: HttpUrl
    container_port: int = Field(..., gt=0, lt=65536, description="Valid port number")

class DeploymentRequest(BaseModel):
    credentials: KubernetesCredentials
    details: DeploymentDetails

class AWSCredentials(BaseModel):
    access_key: str = Field(..., description="AWS Access Key")
    secret_key: str = Field(..., description="AWS Secret Key")

class ECSDeploymentDetails(BaseModel):
    cluster_name: str
    service_name: str
    task_definition_name: str
    region: str
    container_image_url: HttpUrl
    container_port: int = Field(..., gt=0, lt=65536, description="Valid port number")

class ECSDeploymentRequest(BaseModel):
    credentials: AWSCredentials
    details: ECSDeploymentDetails

@app.post("/k8s-deploy")
async def deploy_to_k8s(request: DeploymentRequest):
    try:
        # Decode and load kubeconfig
        kubeconfig_data = base64.b64decode(request.credentials.kubeconfig).decode('utf-8')
        config.load_kube_config_from_dict(kubeconfig_data)

        # Define deployment spec
        deployment = client.V1Deployment(
            metadata=client.V1ObjectMeta(name=f"{request.details.cluster_name}-deployment"),
            spec=client.V1DeploymentSpec(
                replicas=1,
                selector={"matchLabels": {"app": request.details.cluster_name}},
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(labels={"app": request.details.cluster_name}),
                    spec=client.V1PodSpec(containers=[
                        client.V1Container(
                            name=request.details.cluster_name,
                            image=request.details.container_image_url,
                            ports=[client.V1ContainerPort(container_port=request.details.container_port)]
                        )
                    ])
                )
            )
        )

        # Get Kubernetes API client
        api_instance = client.AppsV1Api()
        namespace = "default"  # Modify as necessary

        # Create the deployment
        api_instance.create_namespaced_deployment(namespace=namespace, body=deployment)
        return {"status": "success", "message": "Deployment created successfully"}

    except ValidationError as e:
        raise HTTPException(status_code=400, detail=f"Validation error: {e.errors()}")
    except ApiException as e:
        raise HTTPException(status_code=500, detail=f"Kubernetes API error: {e.reason}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")

@app.post("/ecs-deploy")
async def deploy_to_ecs(request: ECSDeploymentRequest):
    try:
        # Create an ECS client
        ecs_client = boto3.client(
            'ecs',
            aws_access_key_id=request.credentials.access_key,
            aws_secret_access_key=request.credentials.secret_key,
            region_name=request.details.region
        )

        # Register the task definition
        task_definition = ecs_client.register_task_definition(
            family=request.details.task_definition_name,
            containerDefinitions=[
                {
                    'name': request.details.service_name,
                    'image': request.details.container_image_url,
                    'portMappings': [
                        {
                            'containerPort': request.details.container_port,
                            'hostPort': request.details.container_port,
                            'protocol': 'tcp'
                        }
                    ]
                }
            ]
        )

        # Create or update the service
        ecs_client.create_service(
            cluster=request.details.cluster_name,
            serviceName=request.details.service_name,
            taskDefinition=task_definition['taskDefinition']['taskDefinitionArn'],
            desiredCount=1,
            launchType='EC2',
            networkConfiguration={
                'awsvpcConfiguration': {
                    'subnets': [],  # Specify subnets
                    'assignPublicIp': 'ENABLED'
                }
            }
        )

        return {"status": "success", "message": "ECS deployment created successfully"}

    except (BotoCoreError, ClientError) as e:
        raise HTTPException(status_code=500, detail=f"AWS SDK error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")

