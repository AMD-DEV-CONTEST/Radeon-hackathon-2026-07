package com.doublechaintech.onlinebookstoreservice;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.Bean;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;

import io.teaql.core.meta.EntityMetaFactory;
import io.teaql.core.meta.SimpleEntityMetaFactory;
import io.teaql.provider.springjdbc.SpringJdbcSqlExecutor;

@SpringBootApplication
public class App {

  public static void main(String[] args) {
    SpringApplication.run(App.class, args);
  }

  @Bean
  public EntityMetaFactory entityMetaFactory() {
      SimpleEntityMetaFactory factory = new SimpleEntityMetaFactory();
      new EntityMetaRegistry().assemble(factory);
      return factory;
  }

  @Bean
  public SpringJdbcSqlExecutor springJdbcSqlExecutor(NamedParameterJdbcTemplate jdbcTemplate) {
      return new SpringJdbcSqlExecutor(jdbcTemplate);
  }

  @Bean
  public io.teaql.core.DataServiceExecutor dataServiceExecutor(SpringJdbcSqlExecutor executor) {
      return new io.teaql.dataservice.sql.SqlDataServiceExecutor("default", executor);
  }

  @Bean
  public io.teaql.core.DataServiceRegistry dataServiceRegistry(io.teaql.core.DataServiceExecutor dataServiceExecutor) {
      io.teaql.runtime.DefaultDataServiceRegistry registry = new io.teaql.runtime.DefaultDataServiceRegistry();
      registry.register("default", dataServiceExecutor);
      return registry;
  }
}