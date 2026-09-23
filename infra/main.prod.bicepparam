using 'main.bicep'

param environmentName = 'prod'
param namePrefix = 'contoso'
param location = 'eastus2'
param modelDeploymentName = 'gpt-4.1-mini'
param modelCapacity = 100
param tags = {
  owner: 'ai-platform-team'
}
