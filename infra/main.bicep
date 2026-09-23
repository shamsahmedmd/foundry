// One Foundry environment (dev, test or prod): Foundry account + project, model
// deployment and Application Insights for tracing.
// Deploy once per environment into its own resource group (Option A: separate projects).
//
//   az deployment group create -g rg-agents-dev -f infra/main.bicep -p infra/main.dev.bicepparam

targetScope = 'resourceGroup'

@allowed(['dev', 'test', 'prod'])
param environmentName string

@description('Short prefix for resource names (lowercase letters/numbers).')
@minLength(3)
@maxLength(12)
param namePrefix string

param location string = resourceGroup().location

@description('Model deployment name used by the agent. Must match "model" in agent.yaml.')
param modelDeploymentName string = 'gpt-4.1-mini'
param modelName string = 'gpt-4.1-mini'
param modelVersion string = '2025-04-14'
param modelCapacity int = 50

param tags object = {}

var suffix = uniqueString(resourceGroup().id)
var accountName = '${namePrefix}-${environmentName}-${suffix}'
var allTags = union(tags, { environment: environmentName, workload: 'foundry-agents' })

// ------------------------------------------------------------------ observability
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${accountName}'
  location: location
  tags: allTags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: environmentName == 'prod' ? 90 : 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${accountName}'
  location: location
  tags: allTags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
    DisableLocalAuth: false
  }
}

// ------------------------------------------------------------------ Foundry
resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  tags: allTags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: accountName
    allowProjectManagement: true
    disableLocalAuth: true              // Entra ID only, no API keys
    publicNetworkAccess: 'Enabled'
  }
}

resource model 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: modelDeploymentName
  sku: {
    name: 'GlobalStandard'
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  name: 'proj-${environmentName}'
  location: location
  tags: allTags
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: '${namePrefix} agents (${environmentName})'
    description: 'Foundry project for the ${environmentName} environment'
  }
}

// Tracing: connects the project to Application Insights so agent runs are traced.
resource appInsightsConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: project
  name: 'appinsights'
  properties: {
    category: 'AppInsights'
    target: appInsights.id
    authType: 'ApiKey'
    isSharedToAll: true
    credentials: {
      key: appInsights.properties.ConnectionString
    }
    metadata: {
      ApiType: 'Azure'
      ResourceId: appInsights.id
    }
  }
}

output accountName string = account.name
output projectName string = project.name
output foundryProjectEndpoint string = 'https://${accountName}.services.ai.azure.com/api/projects/${project.name}'
output azureOpenAiEndpoint string = 'https://${accountName}.openai.azure.com/'
output projectResourceId string = project.id
output projectPrincipalId string = project.identity.principalId
output modelDeploymentName string = model.name
output appInsightsName string = appInsights.name
